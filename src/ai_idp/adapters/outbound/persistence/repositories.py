from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_idp.adapters.outbound.persistence.leases import execution_scope, require_lease
from ai_idp.adapters.outbound.persistence.models import (
    DecisionRow,
    DocumentRow,
    DocumentUnitRow,
    EvaluationRunRow,
    ExtractionJobRow,
    ExtractionSpecRow,
    FieldAttemptRow,
    FieldResultRow,
    JobQueueRow,
    JobStepRow,
    ModelRequestLeaseRow,
    UsageRecordRow,
)
from ai_idp.domain.enums import (
    DecisionKind,
    DocumentStatus,
    FieldStatus,
    JobStage,
    JobStatus,
    UnitKind,
    VerificationStatus,
)
from ai_idp.domain.errors import DomainError, JobLeaseLostError, JobNotFoundError
from ai_idp.domain.field_paths import assemble_fields
from ai_idp.domain.models import (
    DecisionRecord,
    Document,
    DocumentUnit,
    Evidence,
    ExtractionResult,
    ExtractionRun,
    ExtractionSpecification,
    FieldCandidateAttempt,
    FieldValue,
    JobProgress,
    PipelineConfiguration,
    UsageRecord,
    UsageSummary,
)
from ai_idp.domain.partial_data import project_partial_data
from ai_idp.domain.schema_normalizer import (
    normalize_extraction_schema,
    validate_data_against_schema,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _compute_usage_summary(session: Session, job_id: str) -> UsageSummary:
    rows = session.scalars(select(UsageRecordRow).where(UsageRecordRow.job_id == job_id)).all()
    if not rows:
        return UsageSummary()
    return UsageSummary(
        llm_calls=sum(r.call_count for r in rows),
        tokens_in=sum(r.tokens_in for r in rows),
        tokens_out=sum(r.tokens_out for r in rows),
        estimated_cost_usd=round(sum(r.estimated_cost_usd for r in rows), 6),
        total_latency_ms=sum(r.latency_ms for r in rows),
    )


class SqlAlchemyJobRepository:
    """PostgreSQL/SQLAlchemy implementation of JobRepository with SKIP LOCKED queue leasing."""

    def __init__(
        self, session_factory: sessionmaker[Session], max_concurrent_jobs: int = 2
    ) -> None:
        self._session_factory = session_factory
        self._max_concurrent_jobs = max_concurrent_jobs

    execution_scope = staticmethod(execution_scope)

    def save_document(self, document: Document) -> Document:
        with self._session_factory() as session:
            row = session.get(DocumentRow, document.document_id)
            if row is None:
                row = DocumentRow(
                    id=document.document_id,
                    checksum=document.sha256,
                    filename=document.filename,
                    media_type=document.media_type,
                    bytes=document.bytes_size,
                    storage_key=document.storage_key,
                    status=document.status.value,
                    created_at=document.created_at,
                )
                session.add(row)
            else:
                row.status = document.status.value
            session.commit()
            return document

    def get_document(self, document_id: str) -> Document | None:
        with self._session_factory() as session:
            row = session.get(DocumentRow, document_id)
            if row is None:
                return None
            return Document(
                document_id=row.id,
                filename=row.filename,
                media_type=row.media_type,
                sha256=row.checksum,
                bytes_size=row.bytes,
                storage_key=row.storage_key,
                status=DocumentStatus(row.status),
                created_at=row.created_at,
            )

    def save_units(self, document_id: str, units: list[DocumentUnit]) -> None:
        with self._session_factory() as session:
            existing = session.scalars(
                select(DocumentUnitRow).where(DocumentUnitRow.document_id == document_id)
            ).all()
            if existing:
                return
            for u in units:
                session.add(
                    DocumentUnitRow(
                        document_id=document_id,
                        unit_id=u.unit_id,
                        ordinal=u.ordinal,
                        kind=u.kind.value,
                        locator_json=u.source_locator,
                        text_ref=u.native_text_ref,
                        image_ref=u.image_ref,
                        image_refs_json=u.image_refs,
                        metadata_json=u.metadata,
                    )
                )
            session.commit()

    def get_units(self, document_id: str) -> list[DocumentUnit]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(DocumentUnitRow)
                .where(DocumentUnitRow.document_id == document_id)
                .order_by(DocumentUnitRow.ordinal.asc())
            ).all()
            units = []
            for r in rows:
                image_refs = list(r.image_refs_json or [])
                if not image_refs and r.image_ref:
                    # Recover images already stored by the initial DOCX adapter, too.
                    image_refs = [
                        str(PurePosixPath(r.image_ref).parent / name)
                        for name in (r.metadata_json or {}).get("embedded_images", [])
                    ]
                locator = dict(r.locator_json or {})
                if r.kind == UnitKind.DOCX_BLOCK.value and len(image_refs) > 1:
                    locator.pop("embedded_image", None)
                units.append(
                    DocumentUnit(
                        unit_id=r.unit_id,
                        document_id=r.document_id,
                        ordinal=r.ordinal,
                        kind=UnitKind(r.kind),
                        source_locator=locator,
                        native_text_ref=r.text_ref,
                        image_ref=r.image_ref,
                        image_refs=image_refs,
                        metadata=dict(r.metadata_json or {}),
                    )
                )
            return units

    def save_spec(self, spec: ExtractionSpecification) -> ExtractionSpecification:
        with self._session_factory() as session:
            existing = session.get(ExtractionSpecRow, spec.spec_id)
            if existing is None:
                session.add(
                    ExtractionSpecRow(
                        id=spec.spec_id,
                        schema_json=spec.schema_json,
                        schema_hash=spec.schema_hash,
                        instructions=spec.instructions,
                        created_at=spec.created_at,
                    )
                )
                session.commit()
            return spec

    def get_spec(self, spec_id: str) -> ExtractionSpecification | None:
        with self._session_factory() as session:
            row = session.get(ExtractionSpecRow, spec_id)
            if row is None:
                return None
            spec = normalize_extraction_schema(
                row.schema_json,
                instructions=row.instructions,
                spec_id=row.id,
            )
            spec.created_at = row.created_at
            return spec

    def _row_to_job(self, session: Session, row: ExtractionJobRow) -> ExtractionRun:
        usage = _compute_usage_summary(session, row.id)
        return ExtractionRun(
            job_id=row.id,
            document_id=row.document_id,
            spec_id=row.spec_id,
            status=JobStatus(row.status),
            stage=JobStage(row.stage),
            configuration=PipelineConfiguration.model_validate(row.configuration_json or {}),
            progress=JobProgress.model_validate(row.progress_json or {}),
            usage=usage,
            idempotency_key=row.idempotency_key,
            last_error=row.last_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create_job(self, job: ExtractionRun) -> ExtractionRun:
        now = _utc_now()
        with self._session_factory() as session:
            job_row = ExtractionJobRow(
                id=job.job_id,
                document_id=job.document_id,
                spec_id=job.spec_id,
                status=job.status.value,
                stage=job.stage.value,
                configuration_json=job.configuration.model_dump(mode="json"),
                progress_json=job.progress.model_dump(mode="json"),
                idempotency_key=job.idempotency_key,
                last_error=job.last_error,
                created_at=now,
                updated_at=now,
            )
            queue_row = JobQueueRow(
                job_id=job.job_id,
                status="queued",
                available_at=now,
                attempt_count=0,
            )
            session.add(job_row)
            session.add(queue_row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = (
                    self.get_job_by_idempotency_key(job.idempotency_key)
                    if job.idempotency_key
                    else None
                )
                if existing is None:
                    raise
                old_spec = self.get_spec(existing.spec_id)
                new_spec = self.get_spec(job.spec_id)
                if (
                    existing.document_id != job.document_id
                    or old_spec.schema_hash != new_spec.schema_hash
                    or existing.configuration != job.configuration
                ):
                    raise DomainError(
                        "Idempotency key conflicts with a different request.",
                        code="idempotency_conflict",
                        http_status=409,
                    ) from None
                return existing
            return self._row_to_job(session, job_row)

    def get_job(self, job_id: str) -> ExtractionRun | None:
        with self._session_factory() as session:
            row = session.get(ExtractionJobRow, job_id)
            if row is None:
                return None
            return self._row_to_job(session, row)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> ExtractionRun | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(ExtractionJobRow).where(ExtractionJobRow.idempotency_key == idempotency_key)
            )
            if row is None:
                return None
            return self._row_to_job(session, row)

    def update_job_progress(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        stage: JobStage | None = None,
        progress: JobProgress | None = None,
        last_error: str | None = None,
    ) -> ExtractionRun:
        now = _utc_now()
        with self._session_factory() as session:
            require_lease(session, job_id)
            row = session.get(ExtractionJobRow, job_id)
            if row is None:
                raise JobNotFoundError(f"Job '{job_id}' not found.")
            if row.status == JobStatus.CANCELLED.value and status not in (
                None,
                JobStatus.CANCELLED,
            ):
                # Cooperative cancellation: never overwrite cancelled job state
                return self._row_to_job(session, row)

            if status is not None:
                row.status = status.value
            if stage is not None:
                row.stage = stage.value
            if progress is not None:
                row.progress_json = progress.model_dump(mode="json")
            if last_error is not None:
                row.last_error = last_error
            row.updated_at = now
            session.commit()
            return self._row_to_job(session, row)

    def request_cancel(self, job_id: str) -> ExtractionRun:
        now = _utc_now()
        with self._session_factory() as session:
            q_row = session.scalar(
                select(JobQueueRow).where(JobQueueRow.job_id == job_id).with_for_update()
            )
            row = session.get(ExtractionJobRow, job_id)
            if row is None:
                raise JobNotFoundError(f"Job '{job_id}' not found.")
            if row.status in (
                JobStatus.COMPLETED.value,
                JobStatus.COMPLETED_WITH_UNRESOLVED.value,
                JobStatus.FAILED.value,
            ):
                return self._row_to_job(session, row)
            row.status = JobStatus.CANCELLED.value
            row.stage = JobStage.DONE.value
            row.updated_at = now
            if q_row is not None:
                q_row.status = "cancelled"
                q_row.lease_owner = None
                q_row.lease_until = None
            session.commit()
            return self._row_to_job(session, row)

    def is_cancelled(self, job_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ExtractionJobRow, job_id)
            return row is not None and row.status == JobStatus.CANCELLED.value

    def lease_next_job(self, worker_id: str, lease_seconds: int = 120) -> ExtractionRun | None:
        return self._claim(worker_id, lease_seconds)

    def claim_job(
        self, job_id: str, worker_id: str, lease_seconds: int = 120
    ) -> ExtractionRun | None:
        return self._claim(worker_id, lease_seconds, job_id)

    def _claim(
        self, worker_id: str, lease_seconds: int, job_id: str | None = None
    ) -> ExtractionRun | None:
        now = _utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._session_factory() as session:
            if session.bind.dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(42691022)"))
            elif session.bind.dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            active = session.scalar(
                select(func.count())
                .select_from(JobQueueRow)
                .where(JobQueueRow.status == "leased", JobQueueRow.lease_until > now)
            )
            if active >= self._max_concurrent_jobs:
                return None
            stmt = (
                select(JobQueueRow)
                .where(
                    or_(
                        JobQueueRow.status == "queued",
                        (JobQueueRow.status == "leased") & (JobQueueRow.lease_until < now),
                    ),
                    JobQueueRow.available_at <= now,
                )
                .order_by(JobQueueRow.available_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job_id is not None:
                stmt = stmt.where(JobQueueRow.job_id == job_id)
            q_row = session.scalar(stmt)
            if q_row is None:
                return None

            job_row = session.get(ExtractionJobRow, q_row.job_id)
            if job_row is None or job_row.status in (
                JobStatus.CANCELLED.value,
                JobStatus.COMPLETED.value,
                JobStatus.COMPLETED_WITH_UNRESOLVED.value,
                JobStatus.FAILED.value,
            ):
                q_row.status = job_row.status if job_row else "cancelled"
                session.commit()
                return None

            q_row.status = "leased"
            q_row.lease_owner = worker_id
            q_row.lease_until = lease_until
            q_row.heartbeat_at = now
            q_row.attempt_count += 1
            job_row.status = JobStatus.RUNNING.value
            job_row.updated_at = now
            session.commit()
            return self._row_to_job(session, job_row)

    def heartbeat_job(self, job_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
        now = _utc_now()
        with self._session_factory() as session:
            try:
                q_row = require_lease(session, job_id)
            except JobLeaseLostError:
                return False
            if q_row.lease_owner != worker_id:
                return False
            q_row.heartbeat_at = now
            q_row.lease_until = now + timedelta(seconds=lease_seconds)
            session.commit()
            return True

    def complete_queue_item(
        self,
        job_id: str,
        status: JobStatus,
        error: str | None = None,
        max_attempts: int = 3,
        *,
        retry: bool = True,
    ) -> None:
        now = _utc_now()
        with self._session_factory() as session:
            q_row = require_lease(session, job_id)
            job_row = session.get(ExtractionJobRow, job_id)
            if q_row is not None:
                if retry and status == JobStatus.FAILED and q_row.attempt_count < max_attempts:
                    q_row.status = "queued"
                    q_row.lease_owner = None
                    q_row.lease_until = None
                    q_row.available_at = now + timedelta(seconds=2**q_row.attempt_count)
                    q_row.last_error = error
                    if job_row is not None and job_row.status != JobStatus.CANCELLED.value:
                        job_row.status = JobStatus.PENDING.value
                        job_row.last_error = error
                        job_row.updated_at = now
                else:
                    q_row.status = status.value
                    q_row.lease_owner = None
                    q_row.lease_until = None
                    q_row.last_error = error
                    if job_row is not None:
                        job_row.status = status.value
                        job_row.stage = JobStage.DONE.value
                        job_row.last_error = error
                        job_row.updated_at = now
            session.commit()

    def check_health(self) -> bool:
        try:
            with self._session_factory() as session:
                session.execute(select(JobStepRow.job_id).limit(0))
                session.execute(select(ModelRequestLeaseRow.id).limit(0))
                session.execute(select(UsageRecordRow.call_count).limit(0))
            return True
        except Exception:
            return False


class SqlAlchemyResultRepository:
    """PostgreSQL/SQLAlchemy implementation of ResultRepository."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def load_step(self, job_id: str, step_key: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.get(JobStepRow, (job_id, step_key))
            return row.payload_json if row else None

    def save_step(
        self, job_id: str, step_key: str, payload: dict[str, Any], usage: UsageRecord | None
    ) -> None:
        with self._session_factory() as session:
            require_lease(session, job_id)
            if session.get(JobStepRow, (job_id, step_key)) is not None:
                return
            session.add(JobStepRow(job_id=job_id, step_key=step_key, payload_json=payload))
            if usage is not None and session.get(UsageRecordRow, usage.usage_id) is None:
                session.add(
                    UsageRecordRow(
                        id=usage.usage_id,
                        job_id=job_id,
                        stage=usage.stage,
                        model_id=usage.model_id,
                        tokens_in=usage.tokens_in,
                        tokens_out=usage.tokens_out,
                        estimated_cost_usd=usage.estimated_cost_usd,
                        latency_ms=usage.latency_ms,
                        call_count=usage.call_count,
                        created_at=usage.created_at,
                    )
                )
            session.commit()

    def record_decision(self, record: DecisionRecord) -> None:
        self.record_decisions([record])

    def record_decisions(self, records: list[DecisionRecord]) -> None:
        if not records:
            return
        with self._session_factory() as session:
            for r in records:
                require_lease(session, r.job_id)
                if session.get(DecisionRow, r.decision_id) is not None:
                    continue
                session.add(
                    DecisionRow(
                        id=r.decision_id,
                        job_id=r.job_id,
                        unit_id=r.unit_id,
                        field_path=r.field_path,
                        kind=r.kind.value,
                        model_id=r.model_id,
                        version=r.version,
                        scores_json=r.scores,
                        selected_json=r.selected,
                        latency_ms=r.latency_ms,
                        created_at=r.created_at,
                    )
                )
            session.commit()

    def list_decisions(
        self, job_id: str, *, offset: int = 0, limit: int | None = None
    ) -> list[DecisionRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(DecisionRow)
                .where(DecisionRow.job_id == job_id)
                .order_by(DecisionRow.created_at.asc(), DecisionRow.id.asc())
                .offset(offset)
                .limit(limit)
            ).all()
            return [
                DecisionRecord(
                    decision_id=r.id,
                    job_id=r.job_id,
                    unit_id=r.unit_id,
                    field_path=r.field_path,
                    kind=DecisionKind(r.kind),
                    model_id=r.model_id,
                    version=r.version,
                    scores=dict(r.scores_json or {}),
                    selected=r.selected_json,
                    latency_ms=r.latency_ms,
                    created_at=r.created_at,
                )
                for r in rows
            ]

    def record_field_attempt(self, job_id: str, attempt: FieldCandidateAttempt) -> None:
        with self._session_factory() as session:
            require_lease(session, job_id)
            existing = session.scalar(
                select(FieldAttemptRow).where(
                    FieldAttemptRow.job_id == job_id,
                    FieldAttemptRow.field_path == attempt.field_path,
                    FieldAttemptRow.attempt_number == attempt.attempt_number,
                )
            )
            candidate_payload = {
                "value": attempt.value,
                "sources": [s.model_dump(mode="json") for s in attempt.sources],
                "modality": attempt.modality.value if attempt.modality else None,
            }
            if existing is None:
                session.add(
                    FieldAttemptRow(
                        job_id=job_id,
                        field_path=attempt.field_path,
                        attempt_number=attempt.attempt_number,
                        candidate_json=candidate_payload,
                        model_id=attempt.model_id,
                        status=attempt.status,
                        error=attempt.error,
                        created_at=attempt.created_at,
                    )
                )
            else:
                if (
                    existing.candidate_json != candidate_payload
                    or existing.model_id != attempt.model_id
                ):
                    raise ValueError("A persisted field candidate cannot be overwritten.")
            session.commit()

    def record_usage(self, usage: UsageRecord) -> None:
        with self._session_factory() as session:
            require_lease(session, usage.job_id)
            if session.get(UsageRecordRow, usage.usage_id) is None:
                session.add(
                    UsageRecordRow(
                        id=usage.usage_id,
                        job_id=usage.job_id,
                        stage=usage.stage,
                        model_id=usage.model_id,
                        tokens_in=usage.tokens_in,
                        tokens_out=usage.tokens_out,
                        estimated_cost_usd=usage.estimated_cost_usd,
                        latency_ms=usage.latency_ms,
                        call_count=usage.call_count,
                        created_at=usage.created_at,
                    )
                )
                session.commit()

    def save_final_result(
        self,
        job_id: str,
        status: JobStatus,
        fields: dict[str, FieldValue],
    ) -> None:
        with self._session_factory() as session:
            require_lease(session, job_id)
            job_row = session.get(ExtractionJobRow, job_id)
            if job_row is not None and job_row.status == JobStatus.CANCELLED.value:
                return
            for f_path, fv in fields.items():
                existing = session.get(FieldResultRow, (job_id, f_path))
                sources_list = [s.model_dump(mode="json") for s in fv.sources]
                if existing is None:
                    session.add(
                        FieldResultRow(
                            job_id=job_id,
                            field_path=f_path,
                            final_value_json=fv.value,
                            field_status=fv.status.value,
                            verification_status=(
                                fv.verification.value if fv.verification else None
                            ),
                            score_json=fv.raw_probabilities,
                            sources_json=sources_list,
                            attempt_count=fv.attempt_count,
                            unresolved_reason=fv.unresolved_reason,
                        )
                    )
                else:
                    existing.final_value_json = fv.value
                    existing.field_status = fv.status.value
                    existing.verification_status = (
                        fv.verification.value if fv.verification else None
                    )
                    existing.score_json = fv.raw_probabilities
                    existing.sources_json = sources_list
                    existing.attempt_count = fv.attempt_count
                    existing.unresolved_reason = fv.unresolved_reason
            session.commit()

    def get_extraction_result(
        self,
        job_id: str,
        spec: ExtractionSpecification,
    ) -> ExtractionResult | None:
        with self._session_factory() as session:
            job_row = session.get(ExtractionJobRow, job_id)
            if job_row is None:
                return None
            field_rows = session.scalars(
                select(FieldResultRow).where(FieldResultRow.job_id == job_id)
            ).all()
            attempt_rows = session.scalars(
                select(FieldAttemptRow)
                .where(FieldAttemptRow.job_id == job_id)
                .order_by(FieldAttemptRow.attempt_number.asc())
            ).all()

            attempts_by_path: dict[str, list[FieldCandidateAttempt]] = {}
            for ar in attempt_rows:
                cand = ar.candidate_json or {}
                evs = [
                    Evidence.model_validate(ev)
                    for ev in (cand.get("sources") or [])
                    if isinstance(ev, dict)
                ]
                attempts_by_path.setdefault(ar.field_path, []).append(
                    FieldCandidateAttempt(
                        field_path=ar.field_path,
                        attempt_number=ar.attempt_number,
                        value=cand.get("value"),
                        sources=evs,
                        model_id=ar.model_id,
                        modality=cand.get("modality"),
                        status=ar.status,
                        error=ar.error,
                        created_at=ar.created_at,
                    )
                )

            data: dict[str, Any] = {}
            fields_map: dict[str, FieldValue] = {}
            unresolved_fields: list[str] = []

            row_by_path = {r.field_path: r for r in field_rows}
            paths = list(dict.fromkeys([f.path for f in spec.fields] + list(row_by_path)))
            for path in paths:
                r = row_by_path.get(path)
                if r is None:
                    fields_map[path] = FieldValue(
                        path=path,
                        value=None,
                        status=FieldStatus.UNRESOLVED,
                        unresolved_reason="Field was not processed.",
                    )
                    unresolved_fields.append(path)
                    continue

                f_status = FieldStatus(r.field_status)
                ver_status = (
                    VerificationStatus(r.verification_status) if r.verification_status else None
                )
                sources = [
                    Evidence.model_validate(ev)
                    for ev in (r.sources_json or [])
                    if isinstance(ev, dict)
                ]
                fields_map[path] = FieldValue(
                    path=path,
                    value=r.final_value_json,
                    status=f_status,
                    verification=ver_status,
                    raw_probabilities={
                        str(k): float(v)
                        for k, v in (r.score_json or {}).items()
                        if isinstance(v, (int, float))
                    },
                    sources=sources,
                    attempt_count=r.attempt_count,
                    unresolved_reason=r.unresolved_reason,
                    attempts=attempts_by_path.get(path, []),
                )
                if f_status == FieldStatus.UNRESOLVED:
                    unresolved_fields.append(path)

            data = project_partial_data(assemble_fields(fields_map), spec.schema_json)
            schema_valid, _errs = validate_data_against_schema(data, spec.schema_json)
            usage = _compute_usage_summary(session, job_id)
            return ExtractionResult(
                job_id=job_id,
                status=JobStatus(job_row.status),
                data=data,
                schema_valid=schema_valid,
                schema_errors=_errs,
                fields=fields_map,
                unresolved_fields=unresolved_fields,
                usage=usage,
            )

    def save_evaluation_run(
        self,
        run_id: str,
        dataset_ref: str,
        config_hash: str,
        status: str,
        metrics: dict[str, Any],
    ) -> None:
        with self._session_factory() as session:
            row = session.get(EvaluationRunRow, run_id)
            if row is None:
                session.add(
                    EvaluationRunRow(
                        id=run_id,
                        dataset_ref=dataset_ref,
                        config_hash=config_hash,
                        status=status,
                        metrics_json=metrics,
                    )
                )
            else:
                row.status = status
                row.metrics_json = metrics
            session.commit()
