from __future__ import annotations

from typing import Any

from ai_idp.application.ports.protocols import (
    DecisionEngine,
    DocumentBlobStore,
    DocumentReader,
    ExtractionEngine,
    JobRepository,
    ResultRepository,
    TelemetryPort,
    UnitInputPayload,
)
from ai_idp.domain.enums import (
    FieldStatus,
    JobStage,
    JobStatus,
    Modality,
    PipelineMode,
    VerificationStatus,
)
from ai_idp.domain.errors import BudgetExhaustedError, DocumentNotFoundError, JobNotFoundError
from ai_idp.domain.models import (
    DocumentUnit,
    Evidence,
    ExtractionResult,
    ExtractionRun,
    ExtractionSpecification,
    FieldCandidateAttempt,
    FieldValue,
    JobProgress,
    TargetFieldSpec,
    UsageRecord,
)


def _guess_image_media_type(image_ref: str) -> str:
    lower = image_ref.lower()
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith((".tif", ".tiff")):
        return "image/tiff"
    return "image/png"


class ExtractionPipelineService:
    """Orchestrates the 10-step AI-IDP extraction, verification, and escalation pipeline."""

    def __init__(
        self,
        *,
        blob_store: DocumentBlobStore,
        document_reader: DocumentReader,
        decision_engine: DecisionEngine,
        extraction_engine: ExtractionEngine,
        job_repo: JobRepository,
        result_repo: ResultRepository,
        telemetry: TelemetryPort,
    ) -> None:
        self._blob_store = blob_store
        self._document_reader = document_reader
        self._decision_engine = decision_engine
        self._extraction_engine = extraction_engine
        self._job_repo = job_repo
        self._result_repo = result_repo
        self._telemetry = telemetry

    async def execute_job(self, job_id: str) -> ExtractionResult:
        job = self._job_repo.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"Extraction job '{job_id}' not found.")

        document = self._job_repo.get_document(job.document_id)
        if document is None:
            raise DocumentNotFoundError(f"Document '{job.document_id}' not found.")

        spec = self._job_repo.get_spec(job.spec_id)
        if spec is None:
            raise JobNotFoundError(f"Extraction specification '{job.spec_id}' not found.")

        config = job.configuration
        total_cost = 0.0

        def record_usage(usage: UsageRecord | None) -> None:
            nonlocal total_cost
            if usage is None:
                return
            self._result_repo.record_usage(usage)
            total_cost += usage.estimated_cost_usd
            if total_cost > config.max_job_estimated_cost_usd:
                raise BudgetExhaustedError(
                    f"Job '{job_id}' exceeded estimated cost ceiling "
                    f"(${total_cost:.4f} > ${config.max_job_estimated_cost_usd:.2f})."
                )

        def check_cancelled() -> bool:
            if self._job_repo.is_cancelled(job_id):
                self._job_repo.update_job_progress(
                    job_id, status=JobStatus.CANCELLED, stage=JobStage.DONE
                )
                return True
            return False

        with self._telemetry.span(
            "pipeline.execute_job",
            {"job_id": job_id, "document_id": document.document_id, "mode": config.pipeline_mode},
        ):
            if check_cancelled():
                return self._build_cancelled_result(job_id, spec)

            # Step 1: Prepare or reuse DocumentUnits
            self._job_repo.update_job_progress(
                job_id, status=JobStatus.RUNNING, stage=JobStage.INGESTING
            )
            units = self._job_repo.get_units(document.document_id)
            if not units:
                with self._telemetry.span(
                    "pipeline.normalize_document",
                    {"job_id": job_id, "document_id": document.document_id},
                ):
                    raw_bytes = self._blob_store.get_bytes(document.storage_key)
                    units = self._document_reader.normalize(document, raw_bytes, self._blob_store)
                    self._job_repo.save_units(document.document_id, units)

            progress = JobProgress(
                units_total=len(units),
                units_scored=0,
                fields_completed=0,
                fields_total=len(spec.fields),
            )
            self._job_repo.update_job_progress(job_id, progress=progress)

            unit_payloads = self._load_unit_payloads(units)
            payload_by_id = {p.unit.unit_id: p for p in unit_payloads}
            unit_by_id = {u.unit_id: u for u in units}

            # Step 2 & 3: Relevance Scoring
            self._job_repo.update_job_progress(job_id, stage=JobStage.SCORING_RELEVANCE)
            selected_unit_ids, unselected_unit_ids = await self._score_and_select_units(
                job=job,
                spec=spec,
                unit_payloads=unit_payloads,
                progress=progress,
                record_usage=record_usage,
            )

            if check_cancelled():
                return self._build_cancelled_result(job_id, spec)

            # Step 4 & 5: Modality Selection
            self._job_repo.update_job_progress(job_id, stage=JobStage.SELECTING_MODALITY)
            unit_modalities: dict[str, Modality] = {}
            for uid in selected_unit_ids:
                payload = payload_by_id[uid]
                modality = await self._determine_unit_modality(
                    job=job,
                    spec=spec,
                    payload=payload,
                    record_usage=record_usage,
                )
                unit_modalities[uid] = modality

            if check_cancelled():
                return self._build_cancelled_result(job_id, spec)

            # Step 6 & 7: Structured Extraction
            self._job_repo.update_job_progress(job_id, stage=JobStage.EXTRACTING)
            selected_inputs = [
                (payload_by_id[uid], unit_modalities[uid]) for uid in selected_unit_ids
            ]

            with self._telemetry.span(
                "pipeline.extract_initial",
                {
                    "job_id": job_id,
                    "model_id": config.extraction_model,
                    "units_selected": len(selected_inputs),
                },
            ):
                extraction_batch = await self._extraction_engine.extract_fields(
                    job_id=job_id,
                    spec=spec,
                    target_fields=spec.fields,
                    unit_inputs=selected_inputs,
                    model_id=config.extraction_model,
                    stage_name="extracting",
                )
                record_usage(extraction_batch.usage)

            # Attach canonical locators and record initial attempts
            field_values: dict[str, FieldValue] = {}
            for field_spec in spec.fields:
                raw_val = extraction_batch.data.get(field_spec.name)
                evidences = self._normalize_evidences(
                    extraction_batch.evidence_by_field.get(field_spec.path, []),
                    unit_by_id=unit_by_id,
                    default_unit_ids=selected_unit_ids,
                    has_value=self._is_populated(raw_val),
                )
                attempt = FieldCandidateAttempt(
                    field_path=field_spec.path,
                    attempt_number=1,
                    value=raw_val,
                    sources=evidences,
                    model_id=config.extraction_model,
                    modality=selected_inputs[0][1] if len(selected_inputs) == 1 else None,
                    status="completed",
                )
                self._result_repo.record_field_attempt(job_id, attempt)

                field_values[field_spec.path] = FieldValue(
                    path=field_spec.path,
                    value=raw_val,
                    status=FieldStatus.UNVERIFIED,
                    sources=evidences,
                    attempt_count=1,
                    attempts=[attempt],
                )

            if check_cancelled():
                return self._build_cancelled_result(job_id, spec)

            # Step 8: Independent Field Verification
            should_verify = config.pipeline_mode == PipelineMode.DECISION_LED
            if should_verify:
                self._job_repo.update_job_progress(job_id, stage=JobStage.VERIFYING)
                await self._verify_populated_fields(
                    job=job,
                    spec=spec,
                    field_values=field_values,
                    payload_by_id=payload_by_id,
                    default_unit_ids=selected_unit_ids,
                    record_usage=record_usage,
                )

            # Step 9a: Bounded Escalation for Contradicted / Insufficient Evidence Fields
            if should_verify and config.max_field_extra_attempts > 0:
                needs_escalation = [
                    f
                    for f in spec.fields
                    if self._is_populated(field_values[f.path].value)
                    and field_values[f.path].verification
                    in (VerificationStatus.CONTRADICTED, VerificationStatus.INSUFFICIENT_EVIDENCE)
                ]
                if needs_escalation:
                    self._job_repo.update_job_progress(job_id, stage=JobStage.ESCALATING)
                    await self._run_escalation(
                        job=job,
                        spec=spec,
                        fields_to_escalate=needs_escalation,
                        field_values=field_values,
                        unit_payloads=unit_payloads,
                        payload_by_id=payload_by_id,
                        unit_by_id=unit_by_id,
                        selected_unit_ids=selected_unit_ids,
                        record_usage=record_usage,
                    )

            # Step 9b: Coverage Review for Missing Fields
            missing_fields = [
                f for f in spec.fields if not self._is_populated(field_values[f.path].value)
            ]
            if (
                missing_fields
                and unselected_unit_ids
                and config.max_coverage_reviews > 0
                and config.pipeline_mode
                in (PipelineMode.DECISION_LED, PipelineMode.DECISION_NO_VERIFY)
            ):
                self._job_repo.update_job_progress(job_id, stage=JobStage.REVIEWING_COVERAGE)
                await self._run_coverage_review(
                    job=job,
                    spec=spec,
                    missing_fields=missing_fields,
                    unselected_unit_ids=unselected_unit_ids,
                    field_values=field_values,
                    payload_by_id=payload_by_id,
                    unit_by_id=unit_by_id,
                    should_verify=should_verify,
                    record_usage=record_usage,
                )

            # Step 10: Finalize Field Statuses and Result
            self._job_repo.update_job_progress(job_id, stage=JobStage.FINALIZING)
            unresolved_paths: list[str] = []
            for field_spec in spec.fields:
                fv = field_values[field_spec.path]
                populated = self._is_populated(fv.value)
                if populated:
                    if should_verify:
                        if fv.verification == VerificationStatus.SUPPORTED:
                            fv.status = FieldStatus.VERIFIED
                        else:
                            fv.status = FieldStatus.UNRESOLVED
                            fv.unresolved_reason = (
                                f"Verification returned {fv.verification or 'UNKNOWN'} "
                                f"after {fv.attempt_count} attempt(s)."
                            )
                            unresolved_paths.append(fv.path)
                    else:
                        fv.status = FieldStatus.UNVERIFIED
                else:
                    if field_spec.nullable:
                        fv.status = (
                            FieldStatus.VERIFIED if should_verify else FieldStatus.UNVERIFIED
                        )
                    else:
                        fv.status = FieldStatus.UNRESOLVED
                        fv.unresolved_reason = "Required non-nullable field not found in document."
                        unresolved_paths.append(fv.path)

            progress.fields_completed = len(spec.fields)
            final_status = (
                JobStatus.COMPLETED_WITH_UNRESOLVED if unresolved_paths else JobStatus.COMPLETED
            )
            self._result_repo.save_final_result(job_id, final_status, field_values)
            self._job_repo.update_job_progress(
                job_id,
                status=final_status,
                stage=JobStage.DONE,
                progress=progress,
            )

            result = self._result_repo.get_extraction_result(job_id, spec)
            assert result is not None
            return result

    def _load_unit_payloads(self, units: list[DocumentUnit]) -> list[UnitInputPayload]:
        texts: list[str | None] = []
        for u in units:
            if u.native_text_ref and self._blob_store.exists(u.native_text_ref):
                texts.append(self._blob_store.get_text(u.native_text_ref))
            else:
                texts.append(None)

        payloads: list[UnitInputPayload] = []
        for idx, u in enumerate(units):
            img_bytes: bytes | None = None
            img_media = "image/png"
            if u.image_ref and self._blob_store.exists(u.image_ref):
                img_bytes = self._blob_store.get_bytes(u.image_ref)
                img_media = _guess_image_media_type(u.image_ref)
            prev_excerpt = (texts[idx - 1] or "")[:300] if idx > 0 and texts[idx - 1] else None
            next_excerpt = (
                (texts[idx + 1] or "")[:300] if idx + 1 < len(units) and texts[idx + 1] else None
            )
            payloads.append(
                UnitInputPayload(
                    unit=u,
                    native_text=texts[idx],
                    image_bytes=img_bytes,
                    image_media_type=img_media,
                    prev_excerpt=prev_excerpt,
                    next_excerpt=next_excerpt,
                )
            )
        return payloads

    async def _score_and_select_units(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        unit_payloads: list[UnitInputPayload],
        progress: JobProgress,
        record_usage: Any,
    ) -> tuple[list[str], list[str]]:
        config = job.configuration
        if config.pipeline_mode in (PipelineMode.ALWAYS_VISION, PipelineMode.TEXT_ONLY):
            progress.units_scored = len(unit_payloads)
            self._job_repo.update_job_progress(job.job_id, progress=progress)
            return [p.unit.unit_id for p in unit_payloads], []

        unit_max_score: dict[str, float] = {}
        field_unit_scores: dict[str, list[tuple[float, str]]] = {f.path: [] for f in spec.fields}

        for idx, payload in enumerate(unit_payloads, start=1):
            with self._telemetry.span(
                "pipeline.score_unit_relevance",
                {"job_id": job.job_id, "unit_id": payload.unit.unit_id},
            ):
                rel = await self._decision_engine.score_relevance(
                    job_id=job.job_id,
                    unit_payload=payload,
                    fields=spec.fields,
                    instructions=spec.instructions,
                    model_id=config.decision_model,
                    batch_questions=config.batch_relevance_questions,
                )
                self._result_repo.record_decisions(rel.decision_records)
                record_usage(rel.usage)

                max_s = 0.0
                for f in spec.fields:
                    score = float(rel.field_scores.get(f.path, 0.0))
                    field_unit_scores[f.path].append((score, payload.unit.unit_id))
                    if score > max_s:
                        max_s = score
                unit_max_score[payload.unit.unit_id] = max_s

                progress.units_scored = idx
                self._job_repo.update_job_progress(job.job_id, progress=progress)

        selected_set: set[str] = set()
        for uid, score in unit_max_score.items():
            if score >= config.relevance_threshold:
                selected_set.add(uid)

        # Ensure top-K per field fallback so relevant pages are not missed
        top_k = max(1, config.relevance_top_k)
        for _f_path, scored_list in field_unit_scores.items():
            ranked = sorted(scored_list, key=lambda item: item[0], reverse=True)
            for _score, uid in ranked[:top_k]:
                selected_set.add(uid)

        # Preserve original reading order
        ordered_selected = [p.unit.unit_id for p in unit_payloads if p.unit.unit_id in selected_set]
        unselected_ranked = sorted(
            [p.unit.unit_id for p in unit_payloads if p.unit.unit_id not in selected_set],
            key=lambda uid: unit_max_score.get(uid, 0.0),
            reverse=True,
        )
        return ordered_selected, unselected_ranked

    async def _determine_unit_modality(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        payload: UnitInputPayload,
        record_usage: Any,
    ) -> Modality:
        config = job.configuration
        available = payload.unit.available_modalities
        if config.pipeline_mode == PipelineMode.ALWAYS_VISION:
            if Modality.VISION in available:
                return Modality.VISION
            return available[0] if available else Modality.TEXT

        if config.pipeline_mode == PipelineMode.TEXT_ONLY:
            return Modality.TEXT

        with self._telemetry.span(
            "pipeline.select_unit_modality",
            {"job_id": job.job_id, "unit_id": payload.unit.unit_id},
        ):
            mod_res = await self._decision_engine.select_modality(
                job_id=job.job_id,
                unit_payload=payload,
                fields=spec.fields,
                model_id=config.decision_model,
            )
            self._result_repo.record_decision(mod_res.decision_record)
            record_usage(mod_res.usage)
            return mod_res.decision.modality

    async def _verify_populated_fields(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        field_values: dict[str, FieldValue],
        payload_by_id: dict[str, UnitInputPayload],
        default_unit_ids: list[str],
        record_usage: Any,
    ) -> None:
        fields_to_verify: list[tuple[TargetFieldSpec, Any, list[Evidence]]] = []
        for field_spec in spec.fields:
            fv = field_values[field_spec.path]
            if self._is_populated(fv.value):
                evidences = fv.sources or [
                    Evidence(
                        unit_id=uid,
                        locator=payload_by_id[uid].unit.source_locator,
                    )
                    for uid in default_unit_ids[:2]
                    if uid in payload_by_id
                ]
                fields_to_verify.append((field_spec, fv.value, evidences))

        if not fields_to_verify:
            return

        with self._telemetry.span(
            "pipeline.verify_fields",
            {"job_id": job.job_id, "fields_count": len(fields_to_verify)},
        ):
            ver_batch = await self._decision_engine.verify_fields(
                job_id=job.job_id,
                fields_to_verify=fields_to_verify,
                unit_payloads_by_id=payload_by_id,
                model_id=job.configuration.decision_model,
            )
            self._result_repo.record_decisions(ver_batch.decision_records)
            record_usage(ver_batch.usage)

            for f_path, outcome in ver_batch.outcomes.items():
                if f_path in field_values:
                    field_values[f_path].verification = outcome.status
                    field_values[f_path].raw_probabilities = outcome.raw_probabilities

    async def _run_escalation(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        fields_to_escalate: list[TargetFieldSpec],
        field_values: dict[str, FieldValue],
        unit_payloads: list[UnitInputPayload],
        payload_by_id: dict[str, UnitInputPayload],
        unit_by_id: dict[str, DocumentUnit],
        selected_unit_ids: list[str],
        record_usage: Any,
    ) -> None:
        config = job.configuration
        rich_inputs: list[tuple[UnitInputPayload, Modality]] = []
        for uid in selected_unit_ids:
            payload = payload_by_id[uid]
            avail = payload.unit.available_modalities
            if Modality.TEXT_AND_VISION in avail:
                mod = Modality.TEXT_AND_VISION
            elif Modality.VISION in avail:
                mod = Modality.VISION
            else:
                mod = Modality.TEXT
            rich_inputs.append((payload, mod))

        remaining = list(fields_to_escalate)
        for extra_idx in range(1, config.max_field_extra_attempts + 1):
            if not remaining:
                break
            attempt_num = 1 + extra_idx
            model_to_use = config.escalation_model
            with self._telemetry.span(
                "pipeline.escalate_fields",
                {
                    "job_id": job.job_id,
                    "attempt_number": attempt_num,
                    "model_id": model_to_use,
                    "fields_count": len(remaining),
                },
            ):
                esc_batch = await self._extraction_engine.extract_fields(
                    job_id=job.job_id,
                    spec=spec,
                    target_fields=remaining,
                    unit_inputs=rich_inputs,
                    model_id=model_to_use,
                    stage_name="escalating",
                )
                record_usage(esc_batch.usage)

                verify_subset: list[tuple[TargetFieldSpec, Any, list[Evidence]]] = []
                for f_spec in remaining:
                    fv = field_values[f_spec.path]
                    new_val = esc_batch.data.get(f_spec.name)
                    new_evidences = self._normalize_evidences(
                        esc_batch.evidence_by_field.get(f_spec.path, []),
                        unit_by_id=unit_by_id,
                        default_unit_ids=selected_unit_ids,
                        has_value=self._is_populated(new_val),
                    )
                    attempt = FieldCandidateAttempt(
                        field_path=f_spec.path,
                        attempt_number=attempt_num,
                        value=new_val,
                        sources=new_evidences,
                        model_id=model_to_use,
                        status="completed",
                    )
                    self._result_repo.record_field_attempt(job.job_id, attempt)
                    fv.attempts.append(attempt)
                    fv.attempt_count = len(fv.attempts)
                    fv.value = new_val
                    fv.sources = new_evidences
                    if self._is_populated(new_val):
                        verify_subset.append((f_spec, new_val, new_evidences))

                if verify_subset:
                    ver_res = await self._decision_engine.verify_fields(
                        job_id=job.job_id,
                        fields_to_verify=verify_subset,
                        unit_payloads_by_id=payload_by_id,
                        model_id=config.decision_model,
                    )
                    self._result_repo.record_decisions(ver_res.decision_records)
                    record_usage(ver_res.usage)
                    for f_path, outcome in ver_res.outcomes.items():
                        field_values[f_path].verification = outcome.status
                        field_values[f_path].raw_probabilities = outcome.raw_probabilities

                remaining = [
                    f
                    for f in remaining
                    if self._is_populated(field_values[f.path].value)
                    and field_values[f.path].verification != VerificationStatus.SUPPORTED
                ]

    async def _run_coverage_review(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        missing_fields: list[TargetFieldSpec],
        unselected_unit_ids: list[str],
        field_values: dict[str, FieldValue],
        payload_by_id: dict[str, UnitInputPayload],
        unit_by_id: dict[str, DocumentUnit],
        should_verify: bool,
        record_usage: Any,
    ) -> None:
        config = job.configuration
        review_unit_ids = unselected_unit_ids[: max(2, config.relevance_top_k)]
        if not review_unit_ids:
            return

        review_inputs: list[tuple[UnitInputPayload, Modality]] = []
        for uid in review_unit_ids:
            payload = payload_by_id[uid]
            avail = payload.unit.available_modalities
            mod = (
                Modality.TEXT_AND_VISION
                if Modality.TEXT_AND_VISION in avail
                else (Modality.VISION if Modality.VISION in avail else Modality.TEXT)
            )
            review_inputs.append((payload, mod))

        with self._telemetry.span(
            "pipeline.coverage_review",
            {
                "job_id": job.job_id,
                "missing_fields": len(missing_fields),
                "review_units": len(review_inputs),
            },
        ):
            cov_batch = await self._extraction_engine.extract_fields(
                job_id=job.job_id,
                spec=spec,
                target_fields=missing_fields,
                unit_inputs=review_inputs,
                model_id=config.extraction_model,
                stage_name="reviewing_coverage",
            )
            record_usage(cov_batch.usage)

            newly_populated: list[tuple[TargetFieldSpec, Any, list[Evidence]]] = []
            for f_spec in missing_fields:
                new_val = cov_batch.data.get(f_spec.name)
                if not self._is_populated(new_val):
                    continue
                fv = field_values[f_spec.path]
                evidences = self._normalize_evidences(
                    cov_batch.evidence_by_field.get(f_spec.path, []),
                    unit_by_id=unit_by_id,
                    default_unit_ids=review_unit_ids,
                    has_value=True,
                )
                attempt_num = fv.attempt_count + 1
                attempt = FieldCandidateAttempt(
                    field_path=f_spec.path,
                    attempt_number=attempt_num,
                    value=new_val,
                    sources=evidences,
                    model_id=config.extraction_model,
                    status="completed",
                )
                self._result_repo.record_field_attempt(job.job_id, attempt)
                fv.attempts.append(attempt)
                fv.attempt_count = len(fv.attempts)
                fv.value = new_val
                fv.sources = evidences
                newly_populated.append((f_spec, new_val, evidences))

            if should_verify and newly_populated:
                ver_res = await self._decision_engine.verify_fields(
                    job_id=job.job_id,
                    fields_to_verify=newly_populated,
                    unit_payloads_by_id=payload_by_id,
                    model_id=config.decision_model,
                )
                self._result_repo.record_decisions(ver_res.decision_records)
                record_usage(ver_res.usage)
                for f_path, outcome in ver_res.outcomes.items():
                    field_values[f_path].verification = outcome.status
                    field_values[f_path].raw_probabilities = outcome.raw_probabilities

    @staticmethod
    def _is_populated(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, (list, dict)) and len(value) == 0:
            return False
        return True

    @staticmethod
    def _normalize_evidences(
        evidences: list[Evidence],
        *,
        unit_by_id: dict[str, DocumentUnit],
        default_unit_ids: list[str],
        has_value: bool,
    ) -> list[Evidence]:
        normalized: list[Evidence] = []
        for ev in evidences:
            uid = ev.unit_id
            if uid not in unit_by_id and default_unit_ids:
                uid = default_unit_ids[0]
            unit = unit_by_id.get(uid)
            locator = dict(unit.source_locator) if unit else dict(ev.locator)
            if ev.locator:
                locator.update(ev.locator)
            normalized.append(
                Evidence(
                    unit_id=uid,
                    locator=locator,
                    quote=ev.quote,
                    bounding_box=ev.bounding_box,
                )
            )
        if not normalized and has_value and default_unit_ids:
            first_uid = default_unit_ids[0]
            unit = unit_by_id.get(first_uid)
            normalized.append(
                Evidence(
                    unit_id=first_uid,
                    locator=dict(unit.source_locator) if unit else {},
                )
            )
        return normalized

    def _build_cancelled_result(
        self, job_id: str, spec: ExtractionSpecification
    ) -> ExtractionResult:
        res = self._result_repo.get_extraction_result(job_id, spec)
        if res is not None:
            return res
        return ExtractionResult(job_id=job_id, status=JobStatus.CANCELLED)
