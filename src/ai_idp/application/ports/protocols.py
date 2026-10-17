from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai_idp.domain.enums import JobStage, JobStatus, Modality
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
    ModalityDecision,
    TargetFieldSpec,
    UsageRecord,
    VerificationOutcome,
)


@dataclass(slots=True)
class UnitInputPayload:
    """Prepared content for a single DocumentUnit passed to DecisionEngine or ExtractionEngine."""

    unit: DocumentUnit
    native_text: str | None = None
    image_bytes: bytes | None = None
    image_media_type: str = "image/png"
    prev_excerpt: str | None = None
    next_excerpt: str | None = None
    additional_images: list[tuple[bytes, str]] = field(default_factory=list)
    document_context: str = ""
    extraction_instructions: str = ""
    verification_scope: str = "complete_document"


@dataclass(slots=True)
class RelevanceResult:
    unit_id: str
    field_scores: dict[str, float] = field(default_factory=dict)
    raw_distributions: dict[str, dict[str, float]] = field(default_factory=dict)
    decision_records: list[DecisionRecord] = field(default_factory=list)
    usage: UsageRecord | None = None


@dataclass(slots=True)
class ModalityResult:
    decision: ModalityDecision
    decision_record: DecisionRecord
    usage: UsageRecord | None = None


@dataclass(slots=True)
class VerificationBatchResult:
    outcomes: dict[str, VerificationOutcome] = field(default_factory=dict)
    decision_records: list[DecisionRecord] = field(default_factory=list)
    usage: UsageRecord | None = None


@dataclass(slots=True)
class ExtractionBatchResult:
    data: dict[str, Any] = field(default_factory=dict)
    evidence_by_field: dict[str, list[Evidence]] = field(default_factory=dict)
    model_id: str = ""
    usage: UsageRecord | None = None


class DocumentBlobStore(Protocol):
    def put_bytes(self, key: str, content: bytes) -> str: ...
    def get_bytes(self, key: str) -> bytes: ...
    def get_size(self, key: str) -> int: ...
    def get_text(self, key: str) -> str: ...
    def put_text(self, key: str, text: str) -> str: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def check_health(self) -> bool: ...


class DocumentReader(Protocol):
    def supports(self, media_type: str) -> bool: ...
    def normalize(
        self,
        document: Document,
        raw_bytes: bytes,
        blob_store: DocumentBlobStore,
    ) -> list[DocumentUnit]: ...


class DecisionEngine(Protocol):
    async def score_relevance(
        self,
        job_id: str,
        unit_payload: UnitInputPayload,
        fields: list[TargetFieldSpec],
        instructions: str,
        model_id: str,
        batch_questions: bool = True,
    ) -> RelevanceResult: ...

    async def select_modality(
        self,
        job_id: str,
        unit_payload: UnitInputPayload,
        fields: list[TargetFieldSpec],
        model_id: str,
    ) -> ModalityResult: ...

    async def verify_fields(
        self,
        job_id: str,
        fields_to_verify: list[tuple[TargetFieldSpec, Any, list[Evidence]]],
        unit_payloads_by_id: dict[str, UnitInputPayload],
        model_id: str,
    ) -> VerificationBatchResult: ...


class ExtractionEngine(Protocol):
    async def extract_fields(
        self,
        job_id: str,
        spec: ExtractionSpecification,
        target_fields: list[TargetFieldSpec],
        unit_inputs: list[tuple[UnitInputPayload, Modality]],
        model_id: str,
        stage_name: str = "extracting",
    ) -> ExtractionBatchResult: ...


class JobRepository(Protocol):
    def save_document(self, document: Document) -> Document: ...
    def get_document(self, document_id: str) -> Document | None: ...
    def save_units(self, document_id: str, units: list[DocumentUnit]) -> None: ...
    def get_units(self, document_id: str) -> list[DocumentUnit]: ...
    def save_spec(self, spec: ExtractionSpecification) -> ExtractionSpecification: ...
    def get_spec(self, spec_id: str) -> ExtractionSpecification | None: ...
    def create_job(self, job: ExtractionRun) -> ExtractionRun: ...
    def get_job(self, job_id: str) -> ExtractionRun | None: ...
    def get_job_by_idempotency_key(self, idempotency_key: str) -> ExtractionRun | None: ...
    def update_job_progress(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        stage: JobStage | None = None,
        progress: JobProgress | None = None,
        last_error: str | None = None,
    ) -> ExtractionRun: ...
    def request_cancel(self, job_id: str) -> ExtractionRun: ...
    def is_cancelled(self, job_id: str) -> bool: ...
    def lease_next_job(self, worker_id: str, lease_seconds: int) -> ExtractionRun | None: ...
    def claim_job(
        self, job_id: str, worker_id: str, lease_seconds: int
    ) -> ExtractionRun | None: ...
    def execution_scope(self, job_id: str, worker_id: str) -> AbstractContextManager[None]: ...
    def heartbeat_job(self, job_id: str, worker_id: str, lease_seconds: int) -> bool: ...
    def complete_queue_item(
        self, job_id: str, status: JobStatus, error: str | None = None, *, retry: bool = True
    ) -> None: ...
    def check_health(self) -> bool: ...


class ResultRepository(Protocol):
    def save_evaluation_run(
        self,
        run_id: str,
        dataset_ref: str,
        config_hash: str,
        status: str,
        metrics: dict[str, Any],
    ) -> None: ...
    def load_step(self, job_id: str, step_key: str) -> dict[str, Any] | None: ...
    def save_step(
        self, job_id: str, step_key: str, payload: dict[str, Any], usage: UsageRecord | None
    ) -> None: ...
    def record_decision(self, record: DecisionRecord) -> None: ...
    def record_decisions(self, records: list[DecisionRecord]) -> None: ...
    def list_decisions(
        self, job_id: str, *, offset: int = 0, limit: int | None = None
    ) -> list[DecisionRecord]: ...
    def record_field_attempt(self, job_id: str, attempt: FieldCandidateAttempt) -> None: ...
    def record_usage(self, usage: UsageRecord) -> None: ...
    def save_final_result(
        self,
        job_id: str,
        status: JobStatus,
        fields: dict[str, FieldValue],
    ) -> None: ...
    def get_extraction_result(
        self, job_id: str, spec: ExtractionSpecification
    ) -> ExtractionResult | None: ...


class TelemetryPort(Protocol):
    def span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> AbstractContextManager[Any]: ...
    def record_event(self, name: str, attributes: dict[str, Any] | None = None) -> None: ...
