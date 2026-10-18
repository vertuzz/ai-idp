from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetailResponse(BaseModel):
    error_id: str
    code: str
    message: str


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    media_type: str
    sha256: str
    status: str


class DocumentDetailResponse(BaseModel):
    document_id: str
    filename: str
    media_type: str
    sha256: str
    bytes: int
    status: str
    units_count: int
    conversion_warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class CreateExtractionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str
    schema_def: dict[str, Any] = Field(alias="schema")
    instructions: str = Field(default="", max_length=16000)
    model_profile: Literal["default", "always_vision", "text_only", "decision_no_verify"] = (
        "default"
    )


class JobLinks(BaseModel):
    self: str
    result: str


class CreateExtractionResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    links: JobLinks


class JobProgressResponse(BaseModel):
    units_total: int
    units_scored: int
    fields_completed: int
    fields_total: int


class JobUsageResponse(BaseModel):
    llm_calls: int
    estimated_cost_usd: float
    tokens_in: int = 0
    tokens_out: int = 0
    total_latency_ms: int = 0


class JobStatusResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    stage: str
    progress: JobProgressResponse
    usage: JobUsageResponse
    last_error: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EvidenceItemResponse(BaseModel):
    unit_id: str
    locator: dict[str, Any]
    quote: str | None = None
    raw_value: str | None = None
    bounding_box: dict[str, Any] | None = None
    text_span: dict[str, Any] | None = None


class FieldAttemptResponse(BaseModel):
    attempt_number: int
    value: Any = None
    raw_value: str | None = None
    sources: list[EvidenceItemResponse]
    model_id: str
    modality: str | None = None
    status: str
    error: str | None = None
    check_results: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class FieldResultItemResponse(BaseModel):
    status: str
    verification: str | None = None
    raw_value: str | None = None
    normalization_method: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    unit: str | None = None
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    sources: list[EvidenceItemResponse] = Field(default_factory=list)
    attempt_count: int = 1
    unresolved_reason: str | None = None
    attempts: list[FieldAttemptResponse] = Field(default_factory=list)
    check_results: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionResultResponse(BaseModel):
    job_id: str
    status: str
    data: dict[str, Any]
    schema_valid: bool
    schema_errors: list[str] = Field(default_factory=list)
    fields: dict[str, FieldResultItemResponse]
    unresolved_fields: list[str]
    usage: JobUsageResponse


class DecisionItemResponse(BaseModel):
    decision_id: str
    unit_id: str | None = None
    field_path: str | None = None
    kind: str
    model_id: str
    version: str
    scores: dict[str, Any]
    selected: Any = None
    latency_ms: int
    created_at: datetime


class DecisionsListResponse(BaseModel):
    job_id: str
    decisions: list[DecisionItemResponse]
    offset: int = 0
    limit: int = 100
    next_offset: int | None = None
