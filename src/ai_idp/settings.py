from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", validation_alias="APP_HOST")
    app_port: int = Field(default=8000, validation_alias="APP_PORT")

    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api",
        validation_alias="OPENROUTER_BASE_URL",
    )

    decision_model: str = Field(
        default="perplexity/pplx-decider-v1.2",
        validation_alias=AliasChoices("AI_IDP_DECISION_MODEL", "OPENROUTER_DECISION_MODEL"),
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

    # Safety and operational limits
    max_upload_mib: int = Field(default=200, validation_alias="MAX_UPLOAD_MIB")
    max_pdf_pages: int = Field(default=1000, validation_alias="MAX_PDF_PAGES")
    max_docx_blocks: int = Field(default=1000, validation_alias="MAX_DOCX_BLOCKS")
    max_expanded_mib: int = Field(default=1024, validation_alias="MAX_EXPANDED_MIB")
    max_image_pixels: int = Field(default=40_000_000, validation_alias="MAX_IMAGE_PIXELS")
    max_concurrent_jobs: int = Field(default=2, validation_alias="MAX_CONCURRENT_JOBS")
    max_concurrent_model_requests: int = Field(
        default=6,
        validation_alias="MAX_CONCURRENT_MODEL_REQUESTS",
    )
    max_provider_retries: int = Field(default=3, validation_alias="MAX_PROVIDER_RETRIES")
    max_field_extra_attempts: int = Field(default=2, validation_alias="MAX_FIELD_EXTRA_ATTEMPTS")
    max_coverage_reviews: int = Field(default=1, validation_alias="MAX_COVERAGE_REVIEWS")
    max_job_estimated_cost_usd: float = Field(
        default=10.0,
        validation_alias="MAX_JOB_ESTIMATED_COST_USD",
    )

    # Pipeline tuning parameters
    pdf_render_dpi: int = Field(default=150, validation_alias="PDF_RENDER_DPI")
    relevance_threshold: float = Field(default=0.35, validation_alias="RELEVANCE_THRESHOLD")
    relevance_top_k: int = Field(default=2, validation_alias="RELEVANCE_TOP_K")
    verification_supported_threshold: float = Field(
        default=0.50,
        validation_alias="VERIFICATION_SUPPORTED_THRESHOLD",
    )
    worker_lease_seconds: int = Field(default=120, validation_alias="WORKER_LEASE_SECONDS")
    worker_poll_seconds: float = Field(default=1.0, validation_alias="WORKER_POLL_SECONDS")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mib * 1024 * 1024

    @property
    def max_expanded_bytes(self) -> int:
        return self.max_expanded_mib * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
