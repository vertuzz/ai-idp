from __future__ import annotations

import warnings
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ai_idp.domain.enums import (
    CheckOutcome,
    DecisionKind,
    DocumentStatus,
    FieldStatus,
    JobStage,
    JobStatus,
    Modality,
    PipelineMode,
    UnitKind,
    VerificationStatus,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Document(BaseModel):
    document_id: str
    filename: str
    media_type: str
    sha256: str
    bytes_size: int
    storage_key: str
    status: DocumentStatus = DocumentStatus.STORED
    created_at: datetime = Field(default_factory=utc_now)


class DocumentUnit(BaseModel):
    unit_id: str
    document_id: str
    ordinal: int
    kind: UnitKind
    source_locator: dict[str, Any] = Field(default_factory=dict)
    native_text_ref: str | None = None
    image_ref: str | None = None
    image_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def available_modalities(self) -> list[Modality]:
        modalities: list[Modality] = []
        if self.native_text_ref:
            modalities.append(Modality.TEXT)
        if self.image_ref or self.image_refs:
            modalities.append(Modality.VISION)
        if self.native_text_ref and (self.image_ref or self.image_refs):
            modalities.append(Modality.TEXT_AND_VISION)
        return modalities


class TargetFieldSpec(BaseModel):
    path: str
    name: str
    field_type: str
    description: str = ""
    required: bool = False
    nullable: bool = True
    is_array: bool = False
    raw_schema: dict[str, Any] = Field(default_factory=dict)


with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message='Field name "schema_json"')

    class ExtractionSpecification(BaseModel):
        spec_id: str
        schema_json: dict[str, Any]  # type: ignore[assignment]
        schema_hash: str
        instructions: str = ""
        fields: list[TargetFieldSpec] = Field(default_factory=list)
        output_page: dict[str, Any] | None = None
        created_at: datetime = Field(default_factory=utc_now)


class CandidateUnit(BaseModel):
    unit_id: str
    field_path: str
    relevance_probability: float
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    selected_reason: str = "threshold"


class ModalityDecision(BaseModel):
    unit_id: str
    modality: Modality
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    policy_version: str = "v1"
    available_modalities: list[Modality] = Field(default_factory=list)
    capability_limitation: str | None = None


class TextSpan(BaseModel):
    start: int
    end: int
    text: str | None = None
    artifact_ref: str | None = None
    artifact_sha256: str | None = None


class CheckResult(BaseModel):
    check_name: str
    outcome: CheckOutcome
    reason_code: str
    message: str | None = None
    policy_version: str = "v1"
    evidence_references: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    unit_id: str
    locator: dict[str, Any] = Field(default_factory=dict)
    quote: str | None = None
    raw_value: str | None = None
    bounding_box: dict[str, Any] | None = None
    text_span: TextSpan | None = None


class FieldCandidateAttempt(BaseModel):
    field_path: str
    attempt_number: int
    value: Any = None
    raw_value: str | None = None
    sources: list[Evidence] = Field(default_factory=list)
    model_id: str
    modality: Modality | None = None
    status: str = "completed"
    error: str | None = None
    check_results: list[CheckResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class VerificationOutcome(BaseModel):
    field_path: str
    status: VerificationStatus
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    model_id: str
    rationale: str | None = None


class FieldValue(BaseModel):
    path: str
    value: Any = None
    raw_value: str | None = None
    status: FieldStatus
    verification: VerificationStatus | None = None
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    sources: list[Evidence] = Field(default_factory=list)
    attempt_count: int = 0
    unresolved_reason: str | None = None
    attempts: list[FieldCandidateAttempt] = Field(default_factory=list)
    normalization_method: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    unit: str | None = None
    check_results: list[CheckResult] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    decision_id: str
    job_id: str
    unit_id: str | None = None
    field_path: str | None = None
    kind: DecisionKind
    model_id: str
    version: str = "v1"
    scores: dict[str, Any] = Field(default_factory=dict)
    selected: Any = None
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=utc_now)


class UsageRecord(BaseModel):
    usage_id: str
    job_id: str
    stage: str
    model_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    call_count: int = 1
    created_at: datetime = Field(default_factory=utc_now)


class UsageSummary(BaseModel):
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    total_latency_ms: int = 0


class JobProgress(BaseModel):
    units_total: int = 0
    units_scored: int = 0
    fields_completed: int = 0
    fields_total: int = 0


class PipelineConfiguration(BaseModel):
    model_profile: str = "default"
    pipeline_mode: PipelineMode = PipelineMode.DECISION_LED
    decision_model: str = "perplexity/pplx-decider-v1.2"
    relevance_model: str = "anthropic/claude-haiku-5.5"
    relevance_strategy: Literal["generative", "decisions"] = "decisions"
    extraction_model: str = "anthropic/claude-haiku-5.5"
    escalation_model: str = "google/gemini-4-argon"
    relevance_threshold: float = 0.35
    relevance_top_k: int = 2
    verification_supported_threshold: float = 0.50
    max_field_extra_attempts: int = 2
    max_coverage_reviews: int = 1
    max_job_estimated_cost_usd: float = 10.0
    batch_relevance_questions: bool = True
    relevance_batch_units: int = Field(default=8, ge=1, le=64)
    max_decision_questions_per_call: int = Field(default=24, ge=1, le=256)
    max_parallel_decision_batches: int = Field(default=8, ge=1, le=32)
    pipeline_version: str = "v4"
    max_job_seconds: float = 600
    max_model_calls: int = 250
    max_model_input_bytes: int = 20 * 1024 * 1024
    max_units_per_call: int = 12
    max_decision_images_per_call: int = 8
    max_prepared_input_bytes: int = 256 * 1024 * 1024
    extraction_page_items: int = 25
    max_extraction_parts: int = 128
    max_extracted_fields: int = 50_000
    max_result_bytes: int = 32 * 1024 * 1024
    result_page_bytes: int = 1024 * 1024
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)


class ExtractionRun(BaseModel):
    job_id: str
    document_id: str
    spec_id: str
    status: JobStatus = JobStatus.PENDING
    stage: JobStage = JobStage.QUEUED
    configuration: PipelineConfiguration = Field(default_factory=PipelineConfiguration)
    progress: JobProgress = Field(default_factory=JobProgress)
    usage: UsageSummary = Field(default_factory=UsageSummary)
    idempotency_key: str | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExtractionResult(BaseModel):
    job_id: str
    status: JobStatus
    data: dict[str, Any] = Field(default_factory=dict)
    schema_valid: bool = False
    schema_errors: list[str] = Field(default_factory=list)
    fields: dict[str, FieldValue] = Field(default_factory=dict)
    unresolved_fields: list[str] = Field(default_factory=list)
    usage: UsageSummary = Field(default_factory=UsageSummary)
