from __future__ import annotations

from enum import StrEnum


class DocumentStatus(StrEnum):
    STORED = "stored"
    PREPARED = "prepared"
    FAILED = "failed"


class UnitKind(StrEnum):
    PDF_PAGE = "pdf_page"
    DOCX_BLOCK = "docx_block"
    IMAGE_FRAME = "image_frame"


class Modality(StrEnum):
    TEXT = "TEXT"
    VISION = "VISION"
    TEXT_AND_VISION = "TEXT_AND_VISION"


class VerificationStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class FieldStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    UNRESOLVED = "unresolved"
    MISSING = "missing"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_UNRESOLVED = "completed_with_unresolved"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(StrEnum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    SCORING_RELEVANCE = "scoring_relevance"
    SELECTING_MODALITY = "selecting_modality"
    EXTRACTING = "extracting"
    VERIFYING = "verifying"
    ESCALATING = "escalating"
    REVIEWING_COVERAGE = "reviewing_coverage"
    FINALIZING = "finalizing"
    DONE = "done"


class DecisionKind(StrEnum):
    RELEVANCE = "relevance"
    MODALITY = "modality"
    VERIFICATION = "verification"
    COVERAGE = "coverage"


class PipelineMode(StrEnum):
    DECISION_LED = "decision_led"
    ALWAYS_VISION = "always_vision"
    TEXT_ONLY = "text_only"
    DECISION_NO_VERIFY = "decision_no_verify"


class CheckOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INDETERMINATE = "INDETERMINATE"
