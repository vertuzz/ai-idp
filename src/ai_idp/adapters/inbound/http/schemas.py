from __future__ import annotations

from datetime import datetime
from typing import Any

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
    created_at: datetime


class CreateExtractionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str
    schema_def: dict[str, Any] = Field(alias="schema")
    instructions: str = ""
    model_profile: str = "default"


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


class JobStatusResponse(BaseModel):
    job_id: str
    document_id: str
    status: str
    stage: str
    progress: JobProgressResponse
    usage: JobUsageResponse
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class EvidenceItemResponse(BaseModel):
    unit_id: str
    locator: dict[str, Any]
    quote: str | None = None
    bounding_box: dict[str, Any] | None = None


class FieldResultItemResponse(BaseModel):
    status: str
    verification: str | None = None
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    sources: list[EvidenceItemResponse] = Field(default_factory=list)
    attempt_count: int = 1
    unresolved_reason: str | None = None


class ExtractionResultResponse(BaseModel):
    job_id: str
    status: str
    data: dict[str, Any]
    schema_valid: bool
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
