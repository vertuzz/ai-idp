from __future__ import annotations

import uuid
from typing import Any

from ai_idp.application.ports.protocols import JobRepository, TelemetryPort
from ai_idp.domain.enums import JobStage, JobStatus, PipelineMode
from ai_idp.domain.errors import DocumentNotFoundError, DomainError, InvalidSchemaError
from ai_idp.domain.models import ExtractionRun, JobProgress, PipelineConfiguration
from ai_idp.domain.schema_normalizer import normalize_extraction_schema
from ai_idp.settings import Settings


def build_pipeline_config(
    settings: Settings,
    model_profile: str = "default",
    overrides: dict[str, Any] | None = None,
) -> PipelineConfiguration:
    mode = PipelineMode.DECISION_LED
    if model_profile == "always_vision":
        mode = PipelineMode.ALWAYS_VISION
    elif model_profile == "text_only":
        mode = PipelineMode.TEXT_ONLY
    elif model_profile == "decision_no_verify":
        mode = PipelineMode.DECISION_NO_VERIFY
    elif model_profile != "default":
        raise InvalidSchemaError("Unknown model profile.")

    cfg = PipelineConfiguration(
        model_profile=model_profile,
        pipeline_mode=mode,
        decision_model=settings.decision_model,
        relevance_model=settings.relevance_model,
        relevance_strategy=settings.relevance_strategy,
        extraction_model=settings.extraction_model,
        escalation_model=settings.escalation_model,
        relevance_threshold=settings.relevance_threshold,
        relevance_top_k=settings.relevance_top_k,
        verification_supported_threshold=settings.verification_supported_threshold,
        max_field_extra_attempts=settings.max_field_extra_attempts,
        max_coverage_reviews=settings.max_coverage_reviews,
        max_job_estimated_cost_usd=settings.max_job_estimated_cost_usd,
        max_job_seconds=settings.max_job_seconds,
        max_model_calls=settings.max_model_calls,
        max_model_input_bytes=settings.max_model_input_bytes,
        max_units_per_call=settings.max_units_per_call,
        relevance_batch_units=settings.relevance_batch_units,
        max_decision_questions_per_call=settings.max_decision_questions_per_call,
        max_parallel_decision_batches=settings.max_parallel_decision_batches,
        max_decision_images_per_call=settings.max_decision_images_per_call,
        max_prepared_input_bytes=settings.max_prepared_input_mib * 1024 * 1024,
        extraction_page_items=settings.extraction_page_items,
        max_extraction_parts=settings.max_extraction_parts,
        max_extracted_fields=settings.max_extracted_fields,
        max_result_bytes=settings.max_result_bytes,
        result_page_bytes=settings.result_page_bytes,
        model_parameters={"temperature": 0.0, "max_output_tokens": settings.max_output_tokens},
        prompt_versions={
            "relevance": "v4-page",
            "modality": "v2",
            "extraction": "v2",
            "verification": "v2",
        },
    )
    if overrides:
        cfg = PipelineConfiguration.model_validate({**cfg.model_dump(), **overrides})
    return cfg


class RequestExtractionUseCase:
    """Validates caller schema, records specification, and queues an ExtractionRun."""

    def __init__(
        self,
        *,
        job_repo: JobRepository,
        telemetry: TelemetryPort,
        settings: Settings,
    ) -> None:
        self._job_repo = job_repo
        self._telemetry = telemetry
        self._settings = settings

    def execute(
        self,
        *,
        document_id: str,
        schema_json: dict[str, Any],
        instructions: str = "",
        model_profile: str = "default",
        idempotency_key: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> ExtractionRun:
        spec = normalize_extraction_schema(schema_json, instructions=instructions)
        config = build_pipeline_config(self._settings, model_profile, config_overrides)
        if idempotency_key:
            existing = self._job_repo.get_job_by_idempotency_key(idempotency_key)
            if existing is not None:
                previous = self._job_repo.get_spec(existing.spec_id)
                if (
                    existing.document_id != document_id
                    or previous.schema_hash != spec.schema_hash
                    or existing.configuration != config
                ):
                    raise DomainError(
                        "Idempotency key is already used for a different request.",
                        code="idempotency_conflict",
                        http_status=409,
                    )
                return existing

        document = self._job_repo.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError(f"Document '{document_id}' does not exist.")

        self._job_repo.save_spec(spec)

        units = self._job_repo.get_units(document_id)
        config = build_pipeline_config(
            self._settings,
            model_profile=model_profile,
            overrides=config_overrides,
        )

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = ExtractionRun(
            job_id=job_id,
            document_id=document_id,
            spec_id=spec.spec_id,
            status=JobStatus.PENDING,
            stage=JobStage.QUEUED,
            configuration=config,
            progress=JobProgress(
                units_total=len(units),
                units_scored=0,
                fields_completed=0,
                fields_total=len(spec.fields),
            ),
            idempotency_key=idempotency_key,
        )
        with self._telemetry.span(
            "use_case.request_extraction",
            {"job_id": job_id, "document_id": document_id, "spec_id": spec.spec_id},
        ):
            return self._job_repo.create_job(job)
