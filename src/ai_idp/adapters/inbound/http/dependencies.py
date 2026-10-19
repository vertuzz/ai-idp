from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ai_idp.adapters.outbound.documents.isolated_reader import IsolatedDocumentReader
from ai_idp.adapters.outbound.documents.pdf_artifacts import PdfArtifactStore
from ai_idp.adapters.outbound.openrouter.decisions_client import OpenRouterDecisionEngine
from ai_idp.adapters.outbound.openrouter.extraction_client import PydanticAIExtractionEngine
from ai_idp.adapters.outbound.openrouter.relevance_client import GenerativeRelevanceEngine
from ai_idp.adapters.outbound.openrouter.schema_client import OpenRouterSchemaGenerationEngine
from ai_idp.adapters.outbound.persistence.database import (
    build_engine,
    build_session_factory,
    init_db_schema,
)
from ai_idp.adapters.outbound.persistence.model_limiter import DatabaseModelLimiter
from ai_idp.adapters.outbound.persistence.repositories import (
    SqlAlchemyJobRepository,
    SqlAlchemyResultRepository,
)
from ai_idp.adapters.outbound.persistence.suggestions import SqlAlchemySuggestionRepository
from ai_idp.adapters.outbound.telemetry.otel import OpenTelemetryJsonlAdapter
from ai_idp.application.ports.protocols import (
    DecisionEngine,
    DocumentBlobStore,
    DocumentReader,
    ExtractionEngine,
    JobRepository,
    RelevanceEngine,
    ResultRepository,
    TelemetryPort,
)
from ai_idp.application.ports.schema_suggestion import SchemaDecisionEngine, SchemaGenerationEngine
from ai_idp.application.services.pipeline import ExtractionPipelineService
from ai_idp.application.services.schema_suggestion import SchemaSuggestionService
from ai_idp.application.use_cases.ingest_document import IngestDocumentUseCase
from ai_idp.application.use_cases.inspect_job import InspectJobUseCase
from ai_idp.application.use_cases.request_extraction import RequestExtractionUseCase
from ai_idp.settings import Settings, get_settings


@dataclass
class AppContainer:
    """Dependency container wiring outbound adapters and application services."""

    settings: Settings
    blob_store: DocumentBlobStore
    document_reader: DocumentReader
    decision_engine: DecisionEngine
    extraction_engine: ExtractionEngine
    job_repo: JobRepository
    result_repo: ResultRepository
    telemetry: TelemetryPort
    pipeline_service: ExtractionPipelineService
    ingest_use_case: IngestDocumentUseCase
    request_extraction_use_case: RequestExtractionUseCase
    inspect_job_use_case: InspectJobUseCase
    suggestion_service: SchemaSuggestionService


def build_container(
    settings: Settings | None = None,
    *,
    blob_store: DocumentBlobStore | None = None,
    document_reader: DocumentReader | None = None,
    decision_engine: DecisionEngine | None = None,
    extraction_engine: ExtractionEngine | None = None,
    relevance_engine: RelevanceEngine | None = None,
    job_repo: JobRepository | None = None,
    result_repo: ResultRepository | None = None,
    telemetry: TelemetryPort | None = None,
    schema_generation_engine: SchemaGenerationEngine | None = None,
    schema_decision_engine: SchemaDecisionEngine | None = None,
    create_tables: bool = False,
) -> AppContainer:
    cfg = settings or get_settings()
    engine = build_engine(cfg.database_url)
    if create_tables:
        init_db_schema(engine)
    session_factory = build_session_factory(engine)

    resolved_blob_store = blob_store or PdfArtifactStore(cfg)
    resolved_document_reader = document_reader or IsolatedDocumentReader(cfg)
    resolved_telemetry = telemetry or OpenTelemetryJsonlAdapter(
        cfg.local_telemetry_root,
        max_bytes=cfg.telemetry_max_mib * 1024 * 1024,
        retained_files=cfg.telemetry_retained_files,
    )

    model_semaphore = asyncio.Semaphore(cfg.max_concurrent_model_requests)
    limiter = DatabaseModelLimiter(
        session_factory,
        global_limit=cfg.max_concurrent_model_requests,
        per_model=cfg.per_model_concurrency,
        requests_per_minute=cfg.model_requests_per_minute,
        lease_seconds=cfg.provider_timeout_seconds + 30,
    )
    dec_engine = decision_engine or OpenRouterDecisionEngine(
        max_input_bytes=cfg.max_model_input_bytes,
        api_key=cfg.openrouter_api_key,
        base_url=cfg.openrouter_base_url,
        max_concurrent_requests=cfg.max_concurrent_model_requests,
        max_retries=cfg.max_provider_retries,
        semaphore=model_semaphore,
        limiter=limiter,
        timeout_seconds=cfg.provider_timeout_seconds,
        max_images=cfg.max_decision_images_per_call,
    )
    ext_engine = extraction_engine or PydanticAIExtractionEngine(
        max_input_bytes=cfg.max_model_input_bytes,
        api_key=cfg.openrouter_api_key,
        base_url=cfg.openrouter_base_url,
        max_concurrent_requests=cfg.max_concurrent_model_requests,
        max_retries=cfg.max_provider_retries,
        semaphore=model_semaphore,
        limiter=limiter,
        timeout_seconds=cfg.provider_timeout_seconds,
        max_output_tokens=cfg.max_output_tokens,
    )

    resolved_job_repo = job_repo or SqlAlchemyJobRepository(
        session_factory, cfg.max_concurrent_jobs
    )
    resolved_result_repo = result_repo or SqlAlchemyResultRepository(session_factory)

    pipeline_service = ExtractionPipelineService(
        blob_store=resolved_blob_store,
        document_reader=resolved_document_reader,
        decision_engine=dec_engine,
        relevance_engine=relevance_engine
        or (dec_engine if decision_engine else GenerativeRelevanceEngine(ext_engine)),
        extraction_engine=ext_engine,
        job_repo=resolved_job_repo,
        result_repo=resolved_result_repo,
        telemetry=resolved_telemetry,
        lease_seconds=cfg.worker_lease_seconds,
    )
    ingest_use_case = IngestDocumentUseCase(
        blob_store=resolved_blob_store,
        document_reader=resolved_document_reader,
        job_repo=resolved_job_repo,
        telemetry=resolved_telemetry,
        max_upload_bytes=cfg.max_upload_bytes,
    )
    request_extraction_use_case = RequestExtractionUseCase(
        job_repo=resolved_job_repo,
        telemetry=resolved_telemetry,
        settings=cfg,
    )
    inspect_job_use_case = InspectJobUseCase(
        job_repo=resolved_job_repo,
        result_repo=resolved_result_repo,
    )

    return AppContainer(
        settings=cfg,
        blob_store=resolved_blob_store,
        document_reader=resolved_document_reader,
        decision_engine=dec_engine,
        extraction_engine=ext_engine,
        job_repo=resolved_job_repo,
        result_repo=resolved_result_repo,
        telemetry=resolved_telemetry,
        pipeline_service=pipeline_service,
        ingest_use_case=ingest_use_case,
        request_extraction_use_case=request_extraction_use_case,
        inspect_job_use_case=inspect_job_use_case,
        suggestion_service=SchemaSuggestionService(
            repository=SqlAlchemySuggestionRepository(session_factory, cfg.max_concurrent_jobs),
            job_repo=resolved_job_repo,
            blob_store=resolved_blob_store,
            decision_engine=schema_decision_engine or dec_engine,
            generation_engine=schema_generation_engine
            or OpenRouterSchemaGenerationEngine(ext_engine),
            settings=cfg,
        ),
    )
