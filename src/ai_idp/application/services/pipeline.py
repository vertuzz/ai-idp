from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from typing import Any

from pydantic import TypeAdapter

from ai_idp.application.ports.protocols import (
    DecisionEngine,
    DocumentBlobStore,
    DocumentReader,
    ExtractionBatchResult,
    ExtractionEngine,
    JobRepository,
    ModalityResult,
    RelevanceBatchResult,
    RelevanceEngine,
    ResultRepository,
    TelemetryPort,
    UnitInputPayload,
    VerificationBatchResult,
)
from ai_idp.application.services.batching import unit_batches
from ai_idp.application.services.request_budget import (
    RequestBudget,
    active_job_request_budget,
    active_request_budget,
)
from ai_idp.domain.enums import (
    CheckOutcome,
    FieldStatus,
    JobStage,
    JobStatus,
    Modality,
    PipelineMode,
    UnitKind,
    VerificationStatus,
)
from ai_idp.domain.errors import (
    BudgetExhaustedError,
    DocumentLimitExceededError,
    DocumentNotFoundError,
    DomainError,
    JobLeaseLostError,
    JobNotFoundError,
    JobTimeLimitExceededError,
    ModelOutputLimitExceededError,
    ProviderError,
    RateLimitedError,
)
from ai_idp.domain.field_paths import assemble_fields, concrete_targets, get_pointer
from ai_idp.domain.models import (
    CheckResult,
    DocumentUnit,
    Evidence,
    ExtractionResult,
    ExtractionRun,
    ExtractionSpecification,
    FieldCandidateAttempt,
    FieldValue,
    JobProgress,
    PipelineConfiguration,
    TargetFieldSpec,
    TextSpan,
    UsageRecord,
    VerificationOutcome,
)
from ai_idp.domain.partial_data import project_partial_data
from ai_idp.domain.schema_normalizer import validate_data_against_schema
from ai_idp.domain.validation import (
    build_token_pattern,
    extract_qualifiers,
    extract_units_and_currency,
    validate_field_association,
    validate_source_anchoring,
    validate_typed_value,
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


async def _run_bounded[T](calls: list[Callable[[], Awaitable[T]]], limit: int) -> list[T]:
    """Keep only a bounded number of workers; cancel and drain siblings on failure."""
    pending = iter(enumerate(calls))
    results: list[Any] = [None] * len(calls)

    async def worker() -> None:
        for index, call in pending:
            results[index] = await call()

    tasks = [asyncio.create_task(worker()) for _ in range(min(limit, len(calls)))]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return results


class ExtractionPipelineService:
    """Orchestrates the 10-step AI-IDP extraction, verification, and escalation pipeline."""

    def __init__(
        self,
        *,
        blob_store: DocumentBlobStore,
        document_reader: DocumentReader,
        decision_engine: DecisionEngine,
        relevance_engine: RelevanceEngine | None = None,
        extraction_engine: ExtractionEngine,
        job_repo: JobRepository,
        result_repo: ResultRepository,
        telemetry: TelemetryPort,
        lease_seconds: int = 120,
    ) -> None:
        self._blob_store = blob_store
        self._document_reader = document_reader
        self._decision_engine = decision_engine
        self._relevance_engine = relevance_engine or decision_engine
        self._extraction_engine = extraction_engine
        self._job_repo = job_repo
        self._result_repo = result_repo
        self._telemetry = telemetry
        self._lease_seconds = lease_seconds

    async def execute_job(self, job_id: str, *, lease_owner: str | None = None) -> ExtractionResult:
        """Use the same exclusive, renewable lease for worker, inline and evaluation runs."""
        owner = lease_owner or f"execution_{uuid.uuid4().hex}"
        if lease_owner is None:
            claimed = self._job_repo.claim_job(job_id, owner, self._lease_seconds)
            if claimed is None:
                job = self._job_repo.get_job(job_id)
                if job is None:
                    raise JobNotFoundError(f"Extraction job '{job_id}' not found.")
                if job.status in (
                    JobStatus.COMPLETED,
                    JobStatus.COMPLETED_WITH_UNRESOLVED,
                    JobStatus.CANCELLED,
                ):
                    spec = self._job_repo.get_spec(job.spec_id)
                    assert spec is not None
                    return self._result_repo.get_extraction_result(job_id, spec)
                raise JobLeaseLostError(f"Job '{job_id}' is unavailable or already executing.")

        with self._job_repo.execution_scope(job_id, owner):
            started = self._result_repo.load_step(job_id, "execution:started")
            if started is None:
                started = {"at": datetime.now(UTC).isoformat()}
                self._result_repo.save_step(job_id, "execution:started", started, None)
            remaining = (
                self._job_repo.get_job(job_id).configuration.max_job_seconds
                - (datetime.now(UTC) - datetime.fromisoformat(started["at"])).total_seconds()
            )

            async def timed_execution():
                current = self._job_repo.get_job(job_id)
                budget = RequestBudget(
                    current.configuration.max_model_calls - current.usage.llm_calls,
                    cost_limit=(
                        current.configuration.max_job_estimated_cost_usd
                        - current.usage.estimated_cost_usd
                    ),
                )
                token = active_job_request_budget.set(budget)
                try:
                    return await asyncio.wait_for(self._execute_job(job_id), max(0, remaining))
                except TimeoutError as exc:
                    raise JobTimeLimitExceededError("Extraction job time limit exceeded.") from exc
                finally:
                    active_job_request_budget.reset(token)

            execution = asyncio.create_task(timed_execution())
            heartbeat = asyncio.create_task(self._renew_lease(job_id, owner))
            try:
                done, _ = await asyncio.wait(
                    [execution, heartbeat], return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat in done:
                    await heartbeat
                result = await execution
                self._job_repo.complete_queue_item(job_id, result.status)
                return result
            except JobLeaseLostError:
                if self._job_repo.is_cancelled(job_id):
                    job = self._job_repo.get_job(job_id)
                    spec = self._job_repo.get_spec(job.spec_id)
                    return self._build_cancelled_result(job_id, spec)
                raise
            except Exception as exc:
                retry = not isinstance(exc, DomainError) or isinstance(
                    exc, (ProviderError, RateLimitedError)
                )
                self._job_repo.complete_queue_item(
                    job_id,
                    JobStatus.FAILED,
                    error=exc.message
                    if isinstance(exc, DomainError)
                    else f"Unexpected internal failure ({type(exc).__name__}).",
                    retry=retry,
                )
                raise
            finally:
                for task in (execution, heartbeat):
                    task.cancel()
                await asyncio.gather(execution, heartbeat, return_exceptions=True)

    async def _renew_lease(self, job_id: str, owner: str) -> None:
        while True:
            await asyncio.sleep(max(0.1, self._lease_seconds / 3))
            if not self._job_repo.heartbeat_job(job_id, owner, self._lease_seconds):
                raise JobLeaseLostError(f"Job '{job_id}' lost its lease.")

    async def _model_step[T](
        self, job_id: str, key: str, result_type: type[T], call: Callable[[], Awaitable[T]]
    ) -> T:
        adapter = TypeAdapter(result_type)
        if len(key) > 120:
            key = "step:" + hashlib.sha256(key.encode()).hexdigest()
        saved = self._result_repo.load_step(job_id, key)
        if saved is not None:
            self._telemetry.record_event("model.checkpoint_reused", {"job_id": job_id, "step": key})
            return adapter.validate_python(saved)
        job = self._job_repo.get_job(job_id)
        if job.usage.estimated_cost_usd >= job.configuration.max_job_estimated_cost_usd:
            raise BudgetExhaustedError(f"Job '{job_id}' exhausted its estimated spend budget.")
        if job.usage.llm_calls >= job.configuration.max_model_calls:
            raise BudgetExhaustedError(f"Job '{job_id}' exhausted its model-call budget.")
        if self._job_repo.is_cancelled(job_id):
            raise JobLeaseLostError(f"Job '{job_id}' was cancelled.")
        request_budget = RequestBudget(
            job.configuration.max_model_calls - job.usage.llm_calls,
            parent=active_job_request_budget.get(),
        )
        token = active_request_budget.set(request_budget)
        try:
            result = await call()
        except BaseException:
            if request_budget.used:
                self._result_repo.record_usage(
                    UsageRecord(
                        usage_id=f"use_{uuid.uuid4().hex[:12]}",
                        job_id=job_id,
                        stage="failed_request",
                        model_id="see_configuration",
                        call_count=request_budget.used,
                        estimated_cost_usd=request_budget.reported_cost,
                    )
                )
            raise
        finally:
            active_request_budget.reset(token)
        if getattr(result, "usage", None) and request_budget.used:
            result.usage.call_count = request_budget.used
        usage = getattr(result, "usage", None)
        if usage:
            if request_budget.parent is not None and not request_budget.used:
                # Non-HTTP adapters still participate in the shared execution budget.
                for _ in range(usage.call_count):
                    request_budget.reserve()
            request_budget.report_cost(
                max(0.0, usage.estimated_cost_usd - request_budget.reported_cost)
            )
        self._result_repo.save_step(
            job_id, key, adapter.dump_python(result, mode="json"), getattr(result, "usage", None)
        )
        usage = getattr(result, "usage", None)
        if usage:
            self._telemetry.record_event(
                "model.usage",
                {
                    "job_id": job_id,
                    "step": key,
                    "model_id": usage.model_id,
                    "tokens_in": usage.tokens_in,
                    "tokens_out": usage.tokens_out,
                    "estimated_cost_usd": usage.estimated_cost_usd,
                    "physical_calls": usage.call_count,
                    "latency_ms": usage.latency_ms,
                },
            )
        if (
            self._job_repo.get_job(job_id).usage.estimated_cost_usd
            > job.configuration.max_job_estimated_cost_usd
        ):
            raise BudgetExhaustedError("Job exceeded its estimated spend budget.")
        return result

    async def _extract_bounded(self, *, key: str, **kwargs: Any) -> ExtractionBatchResult:
        from ai_idp.application.services.partitioned_extraction import (
            contains_array,
            extract_partitioned,
        )

        if any(contains_array(f.raw_schema) for f in kwargs["target_fields"]):
            return await extract_partitioned(self, key, **kwargs)
        fields = kwargs["target_fields"]
        if len(fields) > 8:
            data, evidence = {}, {}
            for index in range(0, len(fields), 8):
                result = await self._extract_bounded(
                    key=f"{key}:fields:{index}",
                    **{**kwargs, "target_fields": fields[index : index + 8]},
                )
                data.update(result.data)
                evidence.update(result.evidence_by_field)
            return ExtractionBatchResult(
                data=data, evidence_by_field=evidence, model_id=kwargs["model_id"]
            )
        try:
            return await self._extract_legacy(key=key, **kwargs)
        except ModelOutputLimitExceededError:
            if len(fields) > 1:
                data, evidence = {}, {}
                middle = len(fields) // 2
                for index, group in enumerate((fields[:middle], fields[middle:])):
                    result = await self._extract_bounded(
                        key=f"{key}:split:{index}", **{**kwargs, "target_fields": group}
                    )
                    data.update(result.data)
                    evidence.update(result.evidence_by_field)
                return ExtractionBatchResult(
                    data=data, evidence_by_field=evidence, model_id=kwargs["model_id"]
                )
            target = fields[0]
            if target.field_type == "object":
                from ai_idp.domain.field_paths import escape_segment

                data, evidence = {}, {}
                for name, node in target.raw_schema["properties"].items():
                    path = target.path + "/" + escape_segment(name)
                    types = node["type"] if isinstance(node["type"], list) else [node["type"]]
                    kind = next((t for t in types if t != "null"), "null")
                    child = TargetFieldSpec(
                        path=path,
                        name="part_" + hashlib.sha256(path.encode()).hexdigest()[:24],
                        field_type=kind,
                        raw_schema=node,
                        is_array=kind == "array",
                        description=node.get("description", ""),
                    )
                    result = await self._extract_bounded(
                        key=f"{key}:child:{len(data)}", **{**kwargs, "target_fields": [child]}
                    )
                    data[name] = result.data.get(child.name)
                    evidence.update(result.evidence_by_field)
                evidence[target.path] = [s for sources in evidence.values() for s in sources]
                return ExtractionBatchResult(
                    data={target.name: data},
                    evidence_by_field=evidence,
                    model_id=kwargs["model_id"],
                )
            raise

    async def _extract_legacy(self, *, key: str, **kwargs: Any) -> ExtractionBatchResult:
        job = self._job_repo.get_job(kwargs["job_id"])
        config = job.configuration
        batches = await asyncio.to_thread(
            unit_batches,
            kwargs["unit_inputs"],
            max_units=config.max_units_per_call,
            max_bytes=config.max_model_input_bytes,
        )
        if len(batches) <= 1:
            return await self._model_step(
                job.job_id,
                key,
                ExtractionBatchResult,
                partial(self._extraction_engine.extract_fields, **kwargs),
            )
        results = []
        for idx, batch in enumerate(batches):
            result = await self._model_step(
                job.job_id,
                f"{key}:batch:{idx}",
                ExtractionBatchResult,
                partial(self._extraction_engine.extract_fields, **{**kwargs, "unit_inputs": batch}),
            )
            results.append(result)
        # Merge bounded groups of model candidates. The model chooses values and table
        # continuity; deterministic code never selects a winner or deduplicates line items.
        level = 0
        while len(results) > 1:
            candidate_inputs = []
            for idx, candidate in enumerate(results):
                candidate_inputs.append(
                    (
                        UnitInputPayload(
                            unit=DocumentUnit(
                                unit_id=f"candidate_{level}_{idx}",
                                document_id=job.document_id,
                                ordinal=idx + 1,
                                kind=UnitKind.DOCX_BLOCK,
                            ),
                            native_text=json.dumps(
                                {
                                    "data": candidate.data,
                                    "evidence": {
                                        p: [e.model_dump(mode="json") for e in evs]
                                        for p, evs in candidate.evidence_by_field.items()
                                    },
                                },
                                ensure_ascii=False,
                            ),
                        ),
                        Modality.TEXT,
                    )
                )
            groups = unit_batches(
                candidate_inputs,
                max_units=max(2, config.max_units_per_call),
                max_bytes=config.max_model_input_bytes,
            )
            if len(groups) >= len(results):
                from ai_idp.domain.errors import ModelInputLimitExceededError

                raise ModelInputLimitExceededError("Candidate merge cannot fit two bounded inputs.")
            merged = []
            for idx, group in enumerate(groups):
                merge_spec = kwargs["spec"].model_copy(
                    update={
                        "instructions": (
                            kwargs["spec"].instructions
                            + "\nMerge the candidate extractions below. "
                            "Resolve conflicts using evidence; preserve distinct array items "
                            "and source order. Candidates are intermediate model outputs. "
                            "Cite original source unit IDs inside evidence, never candidate IDs. "
                            "Return null for conflicts that cannot be resolved."
                        )
                    }
                )
                merged.append(
                    await self._model_step(
                        job.job_id,
                        f"{key}:merge:{level}:{idx}",
                        ExtractionBatchResult,
                        partial(
                            self._extraction_engine.extract_fields,
                            **{**kwargs, "spec": merge_spec, "unit_inputs": group},
                        ),
                    )
                )
            results = merged
            level += 1
        return results[0].__class__(
            data=results[0].data,
            evidence_by_field=results[0].evidence_by_field,
            model_id=results[0].model_id,
        )

    async def _verify_bounded(self, *, key: str, **kwargs: Any) -> VerificationBatchResult:
        # Bounded verification values as well as source batches. A container is
        # supported only when every portion is supported; no portion can override
        # a contradiction in another. This checks members, not omission-free coverage.
        small, outcomes, decisions = [], {}, []
        from ai_idp.application.services.verification_parts import value_parts

        for target, value, citations in kwargs["fields_to_verify"]:
            fragments = value_parts(value)
            if len(fragments) == 1 and fragments[0] == value:
                small.append((target, value, citations))
                continue
            results = []
            for index, fragment in enumerate(fragments):
                scoped_target = target.model_copy(
                    update={
                        "description": target.description
                        + " Verify this portion only; other portions are checked separately."
                    }
                )
                # Original source remains available; citations are partitioned as
                # references, never substituted for source or silently truncated.
                result = await self._verify_source_batches(
                    key=f"{key}:portion:{hashlib.sha256(target.path.encode()).hexdigest()[:12]}:{index}",
                    **{
                        **kwargs,
                        "fields_to_verify": [
                            (
                                scoped_target,
                                fragment,
                                [
                                    citation
                                    for citation in citations
                                    if any(
                                        quote and quote in json.dumps(fragment, ensure_ascii=False)
                                        for quote in (citation.raw_value, citation.quote)
                                    )
                                ]
                                or citations,
                            )
                        ],
                    },
                )
                results.append(result.outcomes[target.path])
                decisions.extend(result.decision_records)
            contradicted = next(
                (r for r in results if r.status == VerificationStatus.CONTRADICTED), None
            )
            insufficient = next(
                (r for r in results if r.status != VerificationStatus.SUPPORTED), None
            )
            outcomes[target.path] = contradicted or insufficient or results[0]
            # Completeness of a large list cannot be inferred from valid individual
            # pages. Keep that claim unresolved until independent coverage is checked.
            if outcomes[target.path].status == VerificationStatus.SUPPORTED:
                outcomes[target.path] = outcomes[target.path].model_copy(
                    update={
                        "status": VerificationStatus.INSUFFICIENT_EVIDENCE,
                        "rationale": "Members checked in portions; completeness needs review.",
                    }
                )
        if small:
            result = await self._verify_source_batches(
                key=key, **{**kwargs, "fields_to_verify": small}
            )
            outcomes.update(result.outcomes)
            decisions.extend(result.decision_records)
        return VerificationBatchResult(outcomes=outcomes, decision_records=decisions)

    async def _verify_source_batches(self, *, key: str, **kwargs: Any) -> VerificationBatchResult:
        job = self._job_repo.get_job(kwargs["job_id"])
        config = job.configuration
        payloads = kwargs["unit_payloads_by_id"]
        inputs = []
        for payload in payloads.values():
            has_images = bool(payload.image_count)
            mode = (
                Modality.TEXT_AND_VISION
                if payload.native_text and has_images
                else Modality.VISION
                if has_images
                else Modality.TEXT
            )
            inputs.append((payload, mode))
        batches = await asyncio.to_thread(
            unit_batches,
            inputs,
            max_units=config.max_units_per_call,
            max_bytes=config.max_model_input_bytes,
            max_images=config.max_decision_images_per_call,
        )
        fields = kwargs["fields_to_verify"]
        field_limit = config.max_decision_questions_per_call
        field_groups = [fields[i : i + field_limit] for i in range(0, len(fields), field_limit)]
        if len(batches) <= 1 and len(field_groups) <= 1:
            result = await self._model_step(
                job.job_id,
                key,
                VerificationBatchResult,
                partial(self._decision_engine.verify_fields, **kwargs),
            )
            return self._guard_unavailable_sources(result, fields, payloads)
        outcomes = {}
        records = []
        for gi, group in enumerate(field_groups):
            results = []
            for bi, batch in enumerate(batches):
                scoped = {
                    p.unit.unit_id: replace(p, verification_scope="document_batch")
                    if len(batches) > 1
                    else p
                    for p, _ in batch
                }
                result = await self._model_step(
                    job.job_id,
                    f"{key}:fields:{gi}:sources:{bi}",
                    VerificationBatchResult,
                    partial(
                        self._decision_engine.verify_fields,
                        **{**kwargs, "fields_to_verify": group, "unit_payloads_by_id": scoped},
                    ),
                )
                self._result_repo.record_decisions(result.decision_records)
                records.extend(result.decision_records)
                results.append((set(scoped), result))
            for target, value, citations in group:
                candidates = [r.outcomes[target.path] for _, r in results]
                contradicted = [
                    o for o in candidates if o.status == VerificationStatus.CONTRADICTED
                ]
                if contradicted:
                    chosen = contradicted[0]
                else:
                    absence = value is None or value == [] or value == {}
                    cited_ids = {e.unit_id for e in citations}
                    required = [
                        r.outcomes[target.path] for ids, r in results if absence or ids & cited_ids
                    ]
                    if required and all(o.status == VerificationStatus.SUPPORTED for o in required):
                        chosen = min(
                            required, key=lambda o: o.raw_probabilities.get("SUPPORTED", 0)
                        )
                    else:
                        insufficient = [
                            o
                            for o in candidates
                            if o.status == VerificationStatus.INSUFFICIENT_EVIDENCE
                        ]
                        chosen = (
                            insufficient[0]
                            if insufficient
                            else VerificationOutcome(
                                field_path=target.path,
                                status=VerificationStatus.INSUFFICIENT_EVIDENCE,
                                model_id=config.decision_model,
                                rationale="No complete cited support across source batches.",
                            )
                        )
                outcomes[target.path] = chosen
        return self._guard_unavailable_sources(
            VerificationBatchResult(outcomes=outcomes, decision_records=records), fields, payloads
        )

    @staticmethod
    def _guard_unavailable_sources(result, fields, payloads):
        if any(p.unit.metadata.get("unavailable_images") for p in payloads.values()):
            for target, value, _ in fields:
                if value is None or value == [] or value == {}:
                    outcome = result.outcomes.get(target.path)
                    if outcome and outcome.status == VerificationStatus.SUPPORTED:
                        result.outcomes[target.path] = outcome.model_copy(
                            update={
                                "status": VerificationStatus.INSUFFICIENT_EVIDENCE,
                                "rationale": "Unavailable images prevent confirming absence.",
                            }
                        )
        return result

    async def _execute_job(self, job_id: str) -> ExtractionResult:
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
        if config.pipeline_version != "v4":
            raise DomainError(
                "This job uses an older relevance contract; submit a new extraction job.",
                code="unsupported_pipeline_version",
            )

        def record_usage(usage: UsageRecord | None) -> None:
            if usage is None:
                return
            total_cost = self._job_repo.get_job(job_id).usage.estimated_cost_usd
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
                    units = await asyncio.to_thread(
                        self._document_reader.normalize, document, raw_bytes, self._blob_store
                    )
                    self._job_repo.save_units(document.document_id, units)

            progress = JobProgress(
                units_total=len(units),
                units_scored=0,
                fields_completed=0,
                fields_total=len(spec.fields),
            )
            self._job_repo.update_job_progress(job_id, progress=progress)

            unit_payloads = await asyncio.to_thread(
                self._load_unit_payloads, units, spec.instructions, config.max_prepared_input_bytes
            )
            payload_by_id = {p.unit.unit_id: p for p in unit_payloads}
            unit_by_id = {u.unit_id: u for u in units}

            # Step 2 & 3: Relevance Scoring
            self._job_repo.update_job_progress(job_id, stage=JobStage.SCORING_RELEVANCE)
            selected_unit_ids = await self._score_and_select_units(
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
            modalities = await _run_bounded(
                [
                    partial(
                        self._determine_unit_modality,
                        job=job,
                        spec=spec,
                        payload=payload_by_id[uid],
                        record_usage=record_usage,
                    )
                    for uid in selected_unit_ids
                ],
                config.max_parallel_decision_batches,
            )
            unit_modalities = dict(zip(selected_unit_ids, modalities, strict=True))

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
                extraction_batch = await self._extract_bounded(
                    key="extract:initial",
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
                    payload_by_id=payload_by_id,
                )
                raw_val_str = None
                if evidences:
                    raw_val_str = evidences[0].raw_value or evidences[0].quote

                fv = FieldValue(
                    path=field_spec.path,
                    value=raw_val,
                    raw_value=raw_val_str,
                    status=FieldStatus.UNVERIFIED,
                    sources=evidences,
                    attempt_count=1,
                )
                self._run_mechanical_checks(fv, field_spec, payload_by_id)

                attempt = FieldCandidateAttempt(
                    field_path=field_spec.path,
                    attempt_number=1,
                    value=raw_val,
                    raw_value=raw_val_str,
                    sources=evidences,
                    model_id=config.extraction_model,
                    modality=selected_inputs[0][1] if len(selected_inputs) == 1 else None,
                    status="completed",
                    check_results=list(fv.check_results),
                )
                self._result_repo.record_field_attempt(job_id, attempt)
                fv.attempts = [attempt]
                field_values[field_spec.path] = fv

            if check_cancelled():
                return self._build_cancelled_result(job_id, spec)

            # Step 8: Independent Field Verification
            should_verify = config.pipeline_mode == PipelineMode.DECISION_LED
            if should_verify:
                self._job_repo.update_job_progress(job_id, stage=JobStage.VERIFYING)
                await self._verify_fields(
                    job=job,
                    spec=spec,
                    field_values=field_values,
                    payload_by_id=payload_by_id,
                    record_usage=record_usage,
                )

            # Step 9a: Bounded Escalation for Contradicted / Insufficient Evidence Fields
            if should_verify and config.max_field_extra_attempts > 0:
                needs_escalation = [
                    f
                    for f in spec.fields
                    if field_values[f.path].verification
                    in (VerificationStatus.CONTRADICTED, VerificationStatus.INSUFFICIENT_EVIDENCE)
                    and not (
                        f.is_array
                        and isinstance(field_values[f.path].value, list)
                        and len(field_values[f.path].value) > 25
                    )
                ]
                if needs_escalation:
                    self._job_repo.update_job_progress(job_id, stage=JobStage.ESCALATING)
                    await self._run_escalation(
                        job=job,
                        spec=spec,
                        fields_to_escalate=needs_escalation,
                        field_values=field_values,
                        payload_by_id=payload_by_id,
                        unit_by_id=unit_by_id,
                        record_usage=record_usage,
                    )

            # Step 9b: Coverage Review for Missing Fields
            missing_fields = [
                f
                for f in spec.fields
                if not self._is_populated(field_values[f.path].value)
                and (
                    not f.nullable
                    or field_values[f.path].verification != VerificationStatus.SUPPORTED
                )
            ]
            if (
                missing_fields
                and config.max_coverage_reviews > 0
                and config.pipeline_mode
                in (PipelineMode.DECISION_LED, PipelineMode.DECISION_NO_VERIFY)
            ):
                self._job_repo.update_job_progress(job_id, stage=JobStage.REVIEWING_COVERAGE)
                await self._run_coverage_review(
                    job=job,
                    spec=spec,
                    missing_fields=missing_fields,
                    field_values=field_values,
                    payload_by_id=payload_by_id,
                    unit_by_id=unit_by_id,
                    should_verify=should_verify,
                    record_usage=record_usage,
                )

            # Expand concrete array items and object leaves after root recovery.
            initial_data = assemble_fields(field_values)
            concrete = concrete_targets(
                spec.schema_json, initial_data, max_fields=config.max_extracted_fields
            )
            nested = [f for f in concrete if f.path not in field_values]
            for target in nested:
                root_path = "/" + target.path.split("/")[1]
                root = field_values[root_path]
                _, value = get_pointer(initial_data, target.path)
                sources = self._normalize_evidences(
                    extraction_batch.evidence_by_field.get(target.path, root.sources),
                    unit_by_id=unit_by_id,
                    default_unit_ids=list(payload_by_id),
                    payload_by_id=payload_by_id,
                )
                raw_val_str = sources[0].raw_value or sources[0].quote if sources else None
                fv_leaf = FieldValue(
                    path=target.path,
                    value=value,
                    raw_value=raw_val_str,
                    status=FieldStatus.UNVERIFIED,
                    sources=sources,
                    attempt_count=1,
                )
                self._run_mechanical_checks(fv_leaf, target, payload_by_id)
                attempt = FieldCandidateAttempt(
                    field_path=target.path,
                    attempt_number=1,
                    value=value,
                    raw_value=raw_val_str,
                    sources=sources,
                    model_id=root.attempts[-1].model_id,
                    check_results=list(fv_leaf.check_results),
                )
                self._result_repo.record_field_attempt(job_id, attempt)
                fv_leaf.attempts = [attempt]
                field_values[target.path] = fv_leaf
            if nested and should_verify:
                nested_spec = spec.model_copy(update={"fields": nested})
                await self._verify_fields(
                    job=job,
                    spec=nested_spec,
                    field_values=field_values,
                    payload_by_id=payload_by_id,
                    record_usage=record_usage,
                    key_prefix="leaves:",
                )
                # Recover scalar leaves independently. Replacing a collection would invalidate
                # concrete item identities, so collection recovery is performed at root level.
                recover = [
                    f
                    for f in nested
                    if f.field_type not in ("array", "object")
                    and field_values[f.path].verification != VerificationStatus.SUPPORTED
                ]
                if recover and config.max_field_extra_attempts:
                    await self._run_escalation(
                        job=job,
                        spec=nested_spec,
                        fields_to_escalate=recover,
                        field_values=field_values,
                        payload_by_id=payload_by_id,
                        unit_by_id=unit_by_id,
                        record_usage=record_usage,
                        key_prefix="leaves:",
                    )
                assembled = assemble_fields(field_values)
                changed = []
                for target in concrete:
                    fv = field_values[target.path]
                    _, reconciled = get_pointer(assembled, target.path)
                    if fv.value != reconciled:
                        fv.value = reconciled
                        self._run_mechanical_checks(fv, target, payload_by_id)
                        attempt = FieldCandidateAttempt(
                            field_path=target.path,
                            attempt_number=fv.attempt_count + 1,
                            value=reconciled,
                            raw_value=fv.raw_value,
                            sources=fv.sources,
                            model_id=config.escalation_model,
                            status="reconciled",
                            check_results=list(fv.check_results),
                        )
                        self._result_repo.record_field_attempt(job_id, attempt)
                        fv.attempts.append(attempt)
                        fv.attempt_count += 1
                        changed.append(target)
                if changed:
                    await self._verify_fields(
                        job=job,
                        spec=spec.model_copy(update={"fields": changed}),
                        field_values=field_values,
                        payload_by_id=payload_by_id,
                        record_usage=record_usage,
                        key_prefix="reconciled:",
                    )
            if should_verify:
                await self._verify_collection_coverage(job, concrete, field_values, payload_by_id)
                # A fixed-schema object wrapper adds no independent collection count.
                # Promote a portion-checked wrapper only after every descendant passes.
                for target in sorted(concrete, key=lambda f: -len(f.path)):
                    fv = field_values[target.path]
                    if target.field_type != "object" or fv.verification != (
                        VerificationStatus.INSUFFICIENT_EVIDENCE
                    ):
                        continue
                    if (
                        fv.unresolved_reason
                        != "Members checked in portions; completeness needs review."
                    ):
                        continue
                    if (
                        fv.raw_probabilities.get("SUPPORTED", 0)
                        < config.verification_supported_threshold
                    ):
                        continue
                    children = [
                        child
                        for path, child in field_values.items()
                        if path.startswith(target.path + "/")
                    ]
                    if (
                        children
                        and all(
                            child.verification == VerificationStatus.SUPPORTED
                            and not any(c.outcome == CheckOutcome.FAIL for c in child.check_results)
                            for child in children
                        )
                        and not any(c.outcome == CheckOutcome.FAIL for c in fv.check_results)
                    ):
                        fv.verification = VerificationStatus.SUPPORTED
                        fv.unresolved_reason = None
            spec = spec.model_copy(update={"fields": concrete})
            progress.fields_total = len(concrete)

            # Step 10: Finalize Field Statuses and Result
            self._job_repo.update_job_progress(job_id, stage=JobStage.FINALIZING)
            unresolved_paths: list[str] = []
            for field_spec in spec.fields:
                fv = field_values[field_spec.path]
                populated = self._is_populated(fv.value)
                has_failed_check = any(c.outcome == CheckOutcome.FAIL for c in fv.check_results)
                if populated:
                    if should_verify:
                        if fv.verification == VerificationStatus.SUPPORTED and not has_failed_check:
                            fv.status = FieldStatus.VERIFIED
                        else:
                            fv.status = FieldStatus.UNRESOLVED
                            fv.unresolved_reason = fv.unresolved_reason or (
                                f"Verification returned {fv.verification or 'UNKNOWN'} "
                                f"after {fv.attempt_count} attempt(s)."
                            )
                            unresolved_paths.append(fv.path)
                    else:
                        fv.status = FieldStatus.UNVERIFIED
                else:
                    is_supported = fv.verification == VerificationStatus.SUPPORTED
                    if field_spec.nullable and (
                        not should_verify or (is_supported and not has_failed_check)
                    ):
                        fv.status = (
                            FieldStatus.VERIFIED if should_verify else FieldStatus.UNVERIFIED
                        )
                    else:
                        fv.status = FieldStatus.UNRESOLVED
                        fv.unresolved_reason = fv.unresolved_reason or (
                            "Field absence could not be verified."
                            if field_spec.nullable
                            else "Required non-nullable field not found in document."
                        )
                        unresolved_paths.append(fv.path)

            progress.fields_completed = len(spec.fields)
            schema_ok, _ = validate_data_against_schema(
                project_partial_data(assemble_fields(field_values), spec.schema_json),
                spec.schema_json,
            )
            final_status = (
                JobStatus.COMPLETED_WITH_UNRESOLVED
                if unresolved_paths or not schema_ok
                else JobStatus.COMPLETED
            )
            from ai_idp.application.services.result_views import publish_result_view

            final_data = project_partial_data(assemble_fields(field_values), spec.schema_json)
            if len(json.dumps(final_data, ensure_ascii=True).encode()) > config.max_result_bytes:
                raise DocumentLimitExceededError("Final result-byte limit exceeded.")
            valid, errors = validate_data_against_schema(final_data, spec.schema_json)
            publish_result_view(
                self._result_repo,
                ExtractionResult(
                    job_id=job_id,
                    status=final_status,
                    data=final_data,
                    fields=field_values,
                    schema_valid=valid,
                    schema_errors=errors,
                    unresolved_fields=unresolved_paths,
                    usage=self._job_repo.get_job(job_id).usage,
                ),
                page_bytes=config.result_page_bytes,
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

    def _load_unit_payloads(
        self,
        units: list[DocumentUnit],
        instructions: str = "",
        max_prepared_bytes: int = 256 * 1024 * 1024,
    ) -> list[UnitInputPayload]:
        refs = {
            ref
            for unit in units
            for ref in (
                [unit.native_text_ref]
                if unit.kind == UnitKind.PDF_PAGE
                else [unit.native_text_ref, unit.image_ref, *unit.image_refs]
            )
            if ref
        }
        if sum(self._blob_store.get_size(ref) for ref in refs) > max_prepared_bytes:
            raise DocumentLimitExceededError(
                "Prepared document exceeds the job input memory budget."
            )
        texts: list[str | None] = []
        for u in units:
            if u.native_text_ref:
                texts.append(self._blob_store.get_text(u.native_text_ref))
            else:
                texts.append(None)

        payloads: list[UnitInputPayload] = []
        for idx, u in enumerate(units):
            img_bytes: bytes | None = None
            img_media = "image/png"
            image_refs = list(dict.fromkeys(([u.image_ref] if u.image_ref else []) + u.image_refs))
            lazy_pdf = u.kind == UnitKind.PDF_PAGE
            if image_refs and not lazy_pdf:
                img_bytes = self._blob_store.get_bytes(image_refs[0])
                img_media = _guess_image_media_type(image_refs[0])
            prev_excerpt = texts[idx - 1] if idx > 0 else None
            next_excerpt = texts[idx + 1] if idx + 1 < len(units) else None
            payloads.append(
                UnitInputPayload(
                    unit=u,
                    native_text=texts[idx],
                    image_bytes=img_bytes,
                    image_media_type=img_media,
                    prev_excerpt=prev_excerpt,
                    next_excerpt=next_excerpt,
                    prev_unit_id=units[idx - 1].unit_id if idx > 0 else None,
                    next_unit_id=units[idx + 1].unit_id if idx + 1 < len(units) else None,
                    lazy_image_refs=[(ref, _guess_image_media_type(ref), 0) for ref in image_refs]
                    if lazy_pdf
                    else [],
                    image_loader=self._blob_store.get_bytes if lazy_pdf else None,
                    image_sizer=self._blob_store.get_size if lazy_pdf else None,
                    additional_images=[
                        (self._blob_store.get_bytes(ref), _guess_image_media_type(ref))
                        for ref in image_refs[1:]
                        if not lazy_pdf
                    ],
                    document_context="",
                    extraction_instructions=instructions,
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
    ) -> list[str]:
        config = job.configuration
        if config.pipeline_mode in (PipelineMode.ALWAYS_VISION, PipelineMode.TEXT_ONLY):
            progress.units_scored = len(unit_payloads)
            self._job_repo.update_job_progress(job.job_id, progress=progress)
            return [p.unit.unit_id for p in unit_payloads]

        unit_scores: dict[str, float] = {}
        page_limit = (
            min(config.relevance_batch_units, config.max_decision_questions_per_call)
            if config.batch_relevance_questions
            else 1
        )
        batches = await asyncio.to_thread(
            unit_batches,
            [(payload, Modality.TEXT_AND_VISION) for payload in unit_payloads],
            max_units=page_limit,
            max_bytes=config.max_model_input_bytes,
            max_images=config.max_decision_images_per_call,
        )

        async def score_group(payloads):
            identity = json.dumps([p.unit.unit_id for p in payloads]).encode()
            key = "relevance:v4-page:" + hashlib.sha256(identity).hexdigest()[:32]
            part = await self._model_step(
                job.job_id,
                key,
                RelevanceBatchResult,
                partial(
                    (
                        self._relevance_engine
                        if config.relevance_strategy == "generative"
                        else self._decision_engine
                    ).score_relevance_batch,
                    job_id=job.job_id,
                    unit_payloads=payloads,
                    fields=spec.fields,
                    instructions=spec.instructions,
                    model_id=(
                        config.relevance_model
                        if config.relevance_strategy == "generative"
                        else config.decision_model
                    ),
                ),
            )
            expected_ids = {p.unit.unit_id for p in payloads}
            if set(part.results) != expected_ids or any(
                result.unit_id != uid or not 0 <= result.score <= 1
                for uid, result in part.results.items()
            ):
                raise ProviderError("Relevance response omitted or changed requested units/scores.")
            for uid, result in part.results.items():
                self._result_repo.record_decisions(result.decision_records)
                unit_scores[uid] = result.score
            record_usage(part.usage)
            progress.units_scored = len(unit_scores)
            self._job_repo.update_job_progress(job.job_id, progress=progress)

        await _run_bounded(
            [partial(score_group, [p for p, _ in batch]) for batch in batches],
            config.max_parallel_decision_batches,
        )
        selected_set = {
            uid
            for uid, score in unit_scores.items()
            if (
                score == 1.0
                if config.relevance_strategy == "generative"
                else score >= config.relevance_threshold
            )
        }
        # A document-wide safety floor replaces per-field top-K selection. Ties
        # retain source order, independent of parallel request completion order.
        ranked = sorted(unit_payloads, key=lambda p: -unit_scores[p.unit.unit_id])
        selected_set.update(p.unit.unit_id for p in ranked[: max(1, config.relevance_top_k)])
        ordered_selected = [p.unit.unit_id for p in unit_payloads if p.unit.unit_id in selected_set]
        self._result_repo.save_step(
            job.job_id,
            "routing:selection",
            {
                "selected_unit_ids": ordered_selected,
                "unit_scores": {p.unit.unit_id: unit_scores[p.unit.unit_id] for p in unit_payloads},
                "scope": "any_requested_field",
                "threshold": config.relevance_threshold,
                "strategy": config.relevance_strategy,
                "top_k": config.relevance_top_k,
            },
            None,
        )
        return ordered_selected

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
            # An embedded DOCX image is not a rendering of the semantic text block.
            if payload.unit.kind.value == "docx_block" and Modality.TEXT_AND_VISION in available:
                return Modality.TEXT_AND_VISION
            if Modality.VISION in available:
                return Modality.VISION
            return available[0] if available else Modality.TEXT

        if config.pipeline_mode == PipelineMode.TEXT_ONLY:
            return Modality.TEXT

        with self._telemetry.span(
            "pipeline.select_unit_modality",
            {"job_id": job.job_id, "unit_id": payload.unit.unit_id},
        ):
            mod_res = await self._model_step(
                job.job_id,
                f"modality:{payload.unit.unit_id}",
                ModalityResult,
                lambda: self._decision_engine.select_modality(
                    job_id=job.job_id,
                    unit_payload=payload,
                    fields=spec.fields,
                    model_id=config.decision_model,
                ),
            )
            self._result_repo.record_decision(mod_res.decision_record)
            record_usage(mod_res.usage)
            return mod_res.decision.modality

    async def _verify_collection_coverage(self, job, targets, values, payloads):
        """Check counts independently against every original unit, including unselected ones.

        Counts establish source coverage; per-record/leaf verification separately checks
        values and associations. Neither a model's stop flag nor valid JSON proves coverage.
        """
        from ai_idp.application.services.partitioned_extraction import digest

        parts = [
            p
            for _, p in self._result_repo.list_steps(
                job.job_id, "scope-count:", limit=job.configuration.max_extraction_parts * 4
            )
            if p["stage"] == "extracting"
        ]
        for target in targets:
            parent = values[target.path]
            if not target.is_array or not isinstance(parent.value, list) or not parent.value:
                continue
            if parent.verification == VerificationStatus.CONTRADICTED or any(
                c.outcome == CheckOutcome.FAIL for c in parent.check_results
            ):
                continue
            applicable = [p for p in parts if p["path"] == target.path]
            if not applicable:
                continue
            children = [v for p, v in values.items() if p.startswith(target.path + "/")]
            if any(
                v.verification != VerificationStatus.SUPPORTED
                or any(c.outcome == CheckOutcome.FAIL for c in v.check_results)
                for v in children
            ):
                continue
            outcomes = []
            for uid, payload in payloads.items():
                count = sum(p["count"] for p in applicable if p["source_unit"] == uid)
                count_target = TargetFieldSpec(
                    path=target.path,
                    name="owned_record_count",
                    field_type="integer",
                    raw_schema={"type": "integer"},
                    description=(
                        f"Exact number of distinct requested records for {target.path} "
                        f"({target.description}) whose record STARTS in owned unit {uid}. "
                        "Independently count original source records matching the caller's "
                        "field meaning. Exclude headers and repeated context; include equal "
                        "but distinct records. A candidate count of zero asserts no matching "
                        "record starts here. Do not trust an extractor's count."
                    ),
                )
                result = await self._model_step(
                    job.job_id,
                    f"coverage:{digest(target.path)}:{digest(uid)}",
                    VerificationBatchResult,
                    partial(
                        self._decision_engine.verify_fields,
                        job_id=job.job_id,
                        fields_to_verify=[(count_target, count, [])],
                        unit_payloads_by_id={uid: payload},
                        model_id=job.configuration.decision_model,
                    ),
                )
                self._result_repo.record_decisions(result.decision_records)
                outcome = result.outcomes[target.path]
                outcomes.append(outcome)
            if (
                outcomes
                and all(o.status == VerificationStatus.SUPPORTED for o in outcomes)
                and not any(p.unit.metadata.get("unavailable_images") for p in payloads.values())
            ):
                weakest = min(outcomes, key=lambda o: o.raw_probabilities.get("SUPPORTED", 0))
                self._apply_verification(parent, weakest, job.configuration)
            elif outcomes:
                parent.verification = VerificationStatus.INSUFFICIENT_EVIDENCE
                parent.unresolved_reason = (
                    "Independent source record counts did not establish completeness."
                )

    async def _verify_fields(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        field_values: dict[str, FieldValue],
        payload_by_id: dict[str, UnitInputPayload],
        record_usage: Any,
        key_prefix: str = "",
    ) -> None:
        fields_to_verify: list[tuple[TargetFieldSpec, Any, list[Evidence]]] = []
        for field_spec in spec.fields:
            fv = field_values[field_spec.path]
            self._run_mechanical_checks(fv, field_spec, payload_by_id)
            fields_to_verify.append((field_spec, fv.value, fv.sources))

        if not fields_to_verify:
            return

        with self._telemetry.span(
            "pipeline.verify_fields",
            {"job_id": job.job_id, "fields_count": len(fields_to_verify)},
        ):
            ver_batch = await self._verify_bounded(
                key=f"{key_prefix}verify:initial",
                job_id=job.job_id,
                fields_to_verify=fields_to_verify,
                unit_payloads_by_id=payload_by_id,
                model_id=job.configuration.decision_model,
            )
            self._result_repo.record_decisions(ver_batch.decision_records)
            record_usage(ver_batch.usage)

            for f_path, outcome in ver_batch.outcomes.items():
                if f_path in field_values:
                    self._apply_verification(field_values[f_path], outcome, job.configuration)

    async def _run_escalation(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        fields_to_escalate: list[TargetFieldSpec],
        field_values: dict[str, FieldValue],
        payload_by_id: dict[str, UnitInputPayload],
        unit_by_id: dict[str, DocumentUnit],
        record_usage: Any,
        key_prefix: str = "",
    ) -> None:
        config = job.configuration
        remaining = list(fields_to_escalate)
        for extra_idx in range(1, config.max_field_extra_attempts + 1):
            if not remaining:
                break
            attempt_num = 1 + extra_idx
            model_to_use = config.escalation_model

            # Targeted units: on attempt 1, start strictly with the problematic page(s)
            # cited by the remaining fields. If not cited or after attempt 1, expand to all units.
            cited_uids: list[str] = []
            for f in remaining:
                fv = field_values[f.path]
                for ev in fv.sources:
                    if ev.unit_id in payload_by_id and ev.unit_id not in cited_uids:
                        cited_uids.append(ev.unit_id)

            target_uids = cited_uids if (cited_uids and extra_idx == 1) else list(payload_by_id)

            rich_inputs: list[tuple[UnitInputPayload, Modality]] = []
            for uid in target_uids:
                payload = payload_by_id[uid]
                avail = payload.unit.available_modalities
                if Modality.TEXT_AND_VISION in avail:
                    mod = Modality.TEXT_AND_VISION
                elif Modality.VISION in avail:
                    mod = Modality.VISION
                else:
                    mod = Modality.TEXT
                rich_inputs.append((payload, mod))

            # Targeted context: pass failure reason in field description
            targeted_fields = []
            for f in remaining:
                reason = field_values[f.path].unresolved_reason
                prefix = f.description + " " if f.description else ""
                fail_note = f"[Previous attempt failed: {reason}]" if reason else ""
                desc = (prefix + fail_note).strip()
                targeted_fields.append(f.model_copy(update={"description": desc}))
            with self._telemetry.span(
                "pipeline.escalate_fields",
                {
                    "job_id": job.job_id,
                    "attempt_number": attempt_num,
                    "model_id": model_to_use,
                    "fields_count": len(remaining),
                    "units_count": len(rich_inputs),
                },
            ):
                esc_batch = await self._extract_bounded(
                    key=f"{key_prefix}extract:escalation:{extra_idx}",
                    job_id=job.job_id,
                    spec=spec,
                    target_fields=targeted_fields,
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
                        default_unit_ids=target_uids,
                        payload_by_id=payload_by_id,
                    )
                    raw_val_str = None
                    if new_evidences:
                        raw_val_str = new_evidences[0].raw_value or new_evidences[0].quote
                    fv.raw_value = raw_val_str
                    fv.verification = None
                    fv.raw_probabilities = {}
                    fv.value = new_val
                    fv.sources = new_evidences
                    self._run_mechanical_checks(fv, f_spec, payload_by_id)
                    attempt = FieldCandidateAttempt(
                        field_path=f_spec.path,
                        attempt_number=attempt_num,
                        value=new_val,
                        raw_value=raw_val_str,
                        sources=new_evidences,
                        model_id=model_to_use,
                        status="completed",
                        check_results=list(fv.check_results),
                    )
                    fv.attempts.append(attempt)
                    fv.attempt_count = len(fv.attempts)
                    self._result_repo.record_field_attempt(job.job_id, attempt)
                    verify_subset.append((f_spec, new_val, new_evidences))

                if verify_subset:
                    ver_res = await self._verify_bounded(
                        key=f"{key_prefix}verify:escalation:{extra_idx}",
                        job_id=job.job_id,
                        fields_to_verify=verify_subset,
                        unit_payloads_by_id=payload_by_id,
                        model_id=config.decision_model,
                    )
                    self._result_repo.record_decisions(ver_res.decision_records)
                    record_usage(ver_res.usage)
                    for f_path, outcome in ver_res.outcomes.items():
                        self._apply_verification(field_values[f_path], outcome, config)

                remaining = [
                    f
                    for f in remaining
                    if field_values[f.path].verification != VerificationStatus.SUPPORTED
                    or any(
                        c.outcome == CheckOutcome.FAIL for c in field_values[f.path].check_results
                    )
                ]

    async def _run_coverage_review(
        self,
        *,
        job: ExtractionRun,
        spec: ExtractionSpecification,
        missing_fields: list[TargetFieldSpec],
        field_values: dict[str, FieldValue],
        payload_by_id: dict[str, UnitInputPayload],
        unit_by_id: dict[str, DocumentUnit],
        should_verify: bool,
        record_usage: Any,
    ) -> None:
        config = job.configuration
        review_unit_ids = list(payload_by_id)
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
            cov_batch = await self._extract_bounded(
                key="extract:coverage",
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
                fv = field_values[f_spec.path]
                evidences = self._normalize_evidences(
                    cov_batch.evidence_by_field.get(f_spec.path, []),
                    unit_by_id=unit_by_id,
                    default_unit_ids=review_unit_ids,
                    payload_by_id=payload_by_id,
                )
                raw_val_str = None
                if evidences:
                    raw_val_str = evidences[0].raw_value or evidences[0].quote
                attempt_num = fv.attempt_count + 1
                fv.raw_value = raw_val_str
                fv.verification = None
                fv.raw_probabilities = {}
                fv.value = new_val
                fv.sources = evidences
                self._run_mechanical_checks(fv, f_spec, payload_by_id)
                attempt = FieldCandidateAttempt(
                    field_path=f_spec.path,
                    attempt_number=attempt_num,
                    value=new_val,
                    raw_value=raw_val_str,
                    sources=evidences,
                    model_id=config.extraction_model,
                    status="completed",
                    check_results=list(fv.check_results),
                )
                self._result_repo.record_field_attempt(job.job_id, attempt)
                fv.attempts.append(attempt)
                fv.attempt_count = len(fv.attempts)
                newly_populated.append((f_spec, new_val, evidences))

            if should_verify and newly_populated:
                ver_res = await self._verify_bounded(
                    key="verify:coverage",
                    job_id=job.job_id,
                    fields_to_verify=newly_populated,
                    unit_payloads_by_id=payload_by_id,
                    model_id=config.decision_model,
                )
                self._result_repo.record_decisions(ver_res.decision_records)
                record_usage(ver_res.usage)
                for f_path, outcome in ver_res.outcomes.items():
                    self._apply_verification(field_values[f_path], outcome, config)
            elif not should_verify and newly_populated:
                for f_spec, _, _ in newly_populated:
                    fv = field_values[f_spec.path]
                    failed = [c for c in fv.check_results if c.outcome == CheckOutcome.FAIL]
                    if failed:
                        reasons = ", ".join(c.reason_code for c in failed)
                        fv.unresolved_reason = f"Mechanical check failed: {reasons}"

    @staticmethod
    def _run_mechanical_checks(
        fv: FieldValue,
        field_spec: TargetFieldSpec,
        payload_by_id: dict[str, UnitInputPayload],
    ) -> None:
        fv.check_results = []
        fv.qualifiers = []
        fv.unit = None
        if fv.sources:
            for ev in fv.sources:
                payload = payload_by_id.get(ev.unit_id)
                unit = payload.unit if payload else None
                native_text = payload.native_text if payload else None
                quote_text = ev.raw_value or ev.quote or fv.raw_value
                res = validate_source_anchoring(
                    unit=unit,
                    native_text=native_text,
                    evidence=ev,
                    raw_or_quote=quote_text,
                )
                fv.check_results.append(res)
        elif fv.value is not None and fv.value != [] and fv.value != {}:
            fv.check_results.append(
                CheckResult(
                    check_name="source_anchoring",
                    outcome=CheckOutcome.FAIL,
                    reason_code="MISSING_SOURCE_CITATION",
                    message="Populated field has no source evidence citations.",
                )
            )

        all_texts: list[str] = []
        if fv.sources:
            for s in fv.sources:
                t = s.raw_value or s.quote
                if t and t not in all_texts:
                    all_texts.append(t)
        if fv.raw_value and fv.raw_value not in all_texts:
            all_texts.append(fv.raw_value)

        new_quals: list[str] = []
        new_unit: str | None = None
        for txt in all_texts:
            q = extract_qualifiers(txt)
            if q:
                new_quals.extend(q)
            u = extract_units_and_currency(txt)
            if u and not new_unit:
                new_unit = u
        fv.qualifiers = list(dict.fromkeys(new_quals))
        fv.unit = new_unit

        primary_text = all_texts[0] if all_texts else None
        typed_checks = validate_typed_value(
            value=fv.value,
            raw_text=primary_text,
            field_spec=field_spec,
        )
        fv.check_results.extend(typed_checks)

        assoc_checks = validate_field_association(
            field_name=field_spec.name,
            field_value=fv.value,
        )
        fv.check_results.extend(assoc_checks)

    @staticmethod
    def _apply_verification(
        field: FieldValue, outcome: VerificationOutcome, config: PipelineConfiguration
    ) -> None:
        field.verification = outcome.status
        field.raw_probabilities = outcome.raw_probabilities
        field.unresolved_reason = (
            outcome.rationale if (outcome.status != VerificationStatus.SUPPORTED) else None
        )
        needs_citation = field.value is not None and field.value != [] and field.value != {}
        failed_checks = [c for c in field.check_results if c.outcome == CheckOutcome.FAIL]
        if outcome.status == VerificationStatus.SUPPORTED and (
            outcome.raw_probabilities.get("SUPPORTED", 0.0)
            < config.verification_supported_threshold
            or (needs_citation and not field.sources)
            or bool(failed_checks)
        ):
            field.verification = VerificationStatus.INSUFFICIENT_EVIDENCE
            if failed_checks:
                reasons = ", ".join(c.reason_code for c in failed_checks)
                field.unresolved_reason = f"Mechanical check failed: {reasons}"

    @staticmethod
    def _is_populated(value: Any) -> bool:
        if value is None:
            return False
        return True

    @staticmethod
    def _normalize_evidences(
        evidences: list[Evidence],
        *,
        unit_by_id: dict[str, DocumentUnit],
        default_unit_ids: list[str],
        payload_by_id: dict[str, UnitInputPayload] | None = None,
    ) -> list[Evidence]:
        normalized: list[Evidence] = []
        for ev in evidences:
            uid = ev.unit_id
            unit = unit_by_id.get(uid)
            if unit is None or uid not in default_unit_ids or not unit.available_modalities:
                continue
            locator = dict(ev.locator)
            locator.update(unit.source_locator)
            span = ev.text_span
            target_str = ev.raw_value or ev.quote
            if span is None and target_str and payload_by_id and uid in payload_by_id:
                native_text = payload_by_id[uid].native_text
                if native_text:
                    clean = target_str.strip()
                    pattern = build_token_pattern(clean)
                    matches = [m.span() for m in re.finditer(pattern, native_text)]
                    if len(matches) == 1:
                        h = hashlib.sha256(native_text.encode("utf-8")).hexdigest()
                        span = TextSpan(
                            start=matches[0][0],
                            end=matches[0][1],
                            text=clean,
                            artifact_ref=uid,
                            artifact_sha256=h,
                        )
            locator.pop("cell", None)
            if span is not None:
                matched_cells = [
                    c["cell"]
                    for c in unit.metadata.get("cell_spans", [])
                    if c["start"] <= span.start < span.end <= c["end"]
                ]
                if len(matched_cells) == 1:
                    locator["cell"] = matched_cells[0]
                    calculation = unit.metadata.get("cell_calculations", {}).get(matched_cells[0])
                    if calculation:
                        locator["calculation"] = calculation
            normalized.append(
                Evidence(
                    unit_id=uid,
                    locator=locator,
                    quote=ev.quote,
                    raw_value=ev.raw_value,
                    bounding_box=ev.bounding_box,
                    text_span=span,
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
