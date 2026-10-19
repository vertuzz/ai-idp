from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env."""

    max_formula_cells: int = Field(default=100_000, ge=1, validation_alias="MAX_FORMULA_CELLS")
    max_formula_steps: int = Field(default=100_000, ge=1, validation_alias="MAX_FORMULA_STEPS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")
    api_key: str = Field(default="", validation_alias="AI_IDP_API_KEY")

    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api",
        validation_alias="OPENROUTER_BASE_URL",
    )

    decision_model: str = Field(
        default="perplexity/pplx-decider-v1.2",
        validation_alias=AliasChoices("AI_IDP_DECISION_MODEL", "OPENROUTER_DECISION_MODEL"),
    )
    relevance_model: str = Field(
        default="anthropic/claude-haiku-5.5", validation_alias="AI_IDP_RELEVANCE_MODEL"
    )
    relevance_strategy: Literal["generative", "decisions"] = Field(
        default="decisions", validation_alias="RELEVANCE_STRATEGY"
    )
    extraction_model: str = Field(
        default="anthropic/claude-haiku-5.5",
        validation_alias=AliasChoices("AI_IDP_EXTRACTION_MODEL", "OPENROUTER_EXTRACTION_MODEL"),
    )
    escalation_model: str = Field(
        default="google/gemini-4-argon",
        validation_alias=AliasChoices("AI_IDP_ESCALATION_MODEL", "OPENROUTER_ESCALATION_MODEL"),
    )

    database_url: str = Field(
        # pragma: allowlist nextline secret (public local-development default)
        default="postgresql+psycopg://ai_idp:ai_idp@localhost:5432/ai_idp",
        validation_alias="DATABASE_URL",
    )
    local_storage_root: Path = Field(
        default=Path("./data"),
        validation_alias="LOCAL_STORAGE_ROOT",
    )
    local_telemetry_root: Path = Field(
        default=Path("./telemetry"),
        validation_alias="LOCAL_TELEMETRY_ROOT",
    )
    telemetry_max_mib: int = Field(default=10, ge=1, validation_alias="TELEMETRY_MAX_MIB")
    telemetry_retained_files: int = Field(
        default=20, ge=0, validation_alias="TELEMETRY_RETAINED_FILES"
    )
    worker_shutdown_seconds: float = Field(
        default=30, ge=0, validation_alias="WORKER_SHUTDOWN_SECONDS"
    )

    # Safety and operational limits
    max_upload_mib: int = Field(default=200, validation_alias="MAX_UPLOAD_MIB")
    max_pdf_pages: int = Field(default=1000, validation_alias="MAX_PDF_PAGES")
    max_docx_blocks: int = Field(default=1000, validation_alias="MAX_DOCX_BLOCKS")
    max_spreadsheet_sheets: int = Field(default=128, ge=1)
    max_spreadsheet_cells: int = Field(default=2_000_000, ge=1)
    max_document_units: int = Field(default=10_000, ge=1)
    spreadsheet_rows_per_unit: int = Field(default=25, ge=1, le=100)
    max_unit_text_characters: int = Field(default=16_000, ge=1000)
    max_document_text_characters: int = Field(default=32_000_000, ge=1000)
    extraction_page_items: int = Field(default=25, ge=1, le=100)
    max_extraction_parts: int = Field(default=128, ge=1)
    max_extracted_fields: int = Field(default=50_000, ge=1)
    max_result_bytes: int = Field(default=32 * 1024 * 1024, ge=1024)
    result_page_bytes: int = Field(default=1024 * 1024, ge=1024)
    max_expanded_mib: int = Field(default=1024, validation_alias="MAX_EXPANDED_MIB")
    max_image_pixels: int = Field(default=40_000_000, validation_alias="MAX_IMAGE_PIXELS")
    max_image_frames: int = Field(default=200, ge=1, validation_alias="MAX_IMAGE_FRAMES")
    document_timeout_seconds: float = Field(
        default=600, gt=0, validation_alias="DOCUMENT_TIMEOUT_SECONDS"
    )
    document_memory_mib: int = Field(default=1024, ge=1, validation_alias="DOCUMENT_MEMORY_MIB")
    max_concurrent_jobs: int = Field(default=2, ge=1, validation_alias="MAX_CONCURRENT_JOBS")
    max_concurrent_model_requests: int = Field(
        default=12,
        ge=1,
        validation_alias="MAX_CONCURRENT_MODEL_REQUESTS",
    )
    per_model_concurrency: dict[str, int] = Field(
        default={"*": 8},
        validation_alias="PER_MODEL_CONCURRENCY",
    )
    model_requests_per_minute: dict[str, int] = Field(
        default={"*": 240},
        validation_alias="MODEL_REQUESTS_PER_MINUTE",
    )
    provider_timeout_seconds: float = Field(
        default=120, gt=0, validation_alias="PROVIDER_TIMEOUT_SECONDS"
    )
    max_output_tokens: int = Field(default=8192, ge=128, validation_alias="MAX_OUTPUT_TOKENS")
    max_provider_retries: int = Field(
        default=3, ge=0, le=5, validation_alias="MAX_PROVIDER_RETRIES"
    )
    max_field_extra_attempts: int = Field(
        default=2, ge=0, le=5, validation_alias="MAX_FIELD_EXTRA_ATTEMPTS"
    )
    max_coverage_reviews: int = Field(
        default=1, ge=0, le=1, validation_alias="MAX_COVERAGE_REVIEWS"
    )
    max_job_estimated_cost_usd: float = Field(
        default=10.0,
        validation_alias="MAX_JOB_ESTIMATED_COST_USD",
    )
    max_job_seconds: float = Field(default=600, gt=0, validation_alias="MAX_JOB_SECONDS")
    max_model_calls: int = Field(default=250, ge=1, validation_alias="MAX_MODEL_CALLS")
    max_model_input_bytes: int = Field(
        default=20 * 1024 * 1024, ge=1024, validation_alias="MAX_MODEL_INPUT_BYTES"
    )
    max_units_per_call: int = Field(default=12, ge=2, validation_alias="MAX_UNITS_PER_CALL")
    relevance_batch_units: int = Field(
        default=8, ge=1, le=64, validation_alias="RELEVANCE_BATCH_UNITS"
    )
    max_decision_questions_per_call: int = Field(
        default=24, ge=1, le=256, validation_alias="MAX_DECISION_QUESTIONS_PER_CALL"
    )
    max_parallel_decision_batches: int = Field(
        default=8, ge=1, le=32, validation_alias="MAX_PARALLEL_DECISION_BATCHES"
    )
    max_decision_images_per_call: int = Field(
        default=8, ge=1, validation_alias="MAX_DECISION_IMAGES_PER_CALL"
    )
    max_prepared_input_mib: int = Field(
        default=256, ge=1, validation_alias="MAX_PREPARED_INPUT_MIB"
    )

    # Pipeline tuning parameters
    pdf_render_dpi: int = Field(default=150, validation_alias="PDF_RENDER_DPI")
    relevance_threshold: float = Field(default=0.35, validation_alias="RELEVANCE_THRESHOLD")
    relevance_top_k: int = Field(default=2, validation_alias="RELEVANCE_TOP_K")
    verification_supported_threshold: float = Field(
        default=0.50,
        ge=0,
        le=1,
        validation_alias="VERIFICATION_SUPPORTED_THRESHOLD",
    )
    worker_lease_seconds: int = Field(default=120, ge=1, validation_alias="WORKER_LEASE_SECONDS")
    worker_poll_seconds: float = Field(default=1.0, ge=0.01, validation_alias="WORKER_POLL_SECONDS")

    @field_validator("per_model_concurrency", "model_requests_per_minute")
    @classmethod
    def positive_model_limits(cls, values: dict[str, int]) -> dict[str, int]:
        if any(value < 1 for value in values.values()):
            raise ValueError("Per-model limits must be positive integers.")
        return values

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mib * 1024 * 1024

    @property
    def max_expanded_bytes(self) -> int:
        return self.max_expanded_mib * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
