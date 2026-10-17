from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ai_idp.adapters.outbound.documents.composite_reader import CompositeDocumentReader
from ai_idp.adapters.outbound.openrouter.decisions_client import OpenRouterDecisionEngine
from ai_idp.adapters.outbound.openrouter.extraction_client import PydanticAIExtractionEngine
from ai_idp.adapters.outbound.persistence.database import (
    build_engine,
    build_session_factory,
    init_db_schema,
)
from ai_idp.adapters.outbound.persistence.repositories import (
    SqlAlchemyJobRepository,
    SqlAlchemyResultRepository,
)
from ai_idp.adapters.outbound.storage.local import LocalDocumentBlobStore
from ai_idp.adapters.outbound.telemetry.otel import OpenTelemetryJsonlAdapter
from ai_idp.application.ports.protocols import (
    DecisionEngine,
    DocumentBlobStore,
    DocumentReader,
    ExtractionEngine,
    JobRepository,
    ResultRepository,
    TelemetryPort,
)
from ai_idp.application.services.pipeline import ExtractionPipelineService
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


def build_container(
    settings: Settings | None = None,
    *,
    decision_engine: DecisionEngine | None = None,
    extraction_engine: ExtractionEngine | None = None,
    create_tables: bool = False,
) -> AppContainer:
    cfg = settings or get_settings()
    engine = build_engine(cfg.database_url)
    if create_tables:
        init_db_schema(engine)
    session_factory = build_session_factory(engine)

    blob_store = LocalDocumentBlobStore(cfg.local_storage_root)
    document_reader = CompositeDocumentReader.from_settings(cfg)
    telemetry = OpenTelemetryJsonlAdapter(cfg.local_telemetry_root)

    model_semaphore = asyncio.Semaphore(cfg.max_concurrent_model_requests)
    dec_engine = decision_engine or OpenRouterDecisionEngine(
        api_key=cfg.openrouter_api_key,
        base_url=cfg.openrouter_base_url,
        max_concurrent_requests=cfg.max_concurrent_model_requests,
        max_retries=cfg.max_provider_retries,
        semaphore=model_semaphore,
    )
    ext_engine = extraction_engine or PydanticAIExtractionEngine(
        api_key=cfg.openrouter_api_key,
        base_url=cfg.openrouter_base_url,
        max_concurrent_requests=cfg.max_concurrent_model_requests,
        max_retries=cfg.max_provider_retries,
        semaphore=model_semaphore,
    )

    job_repo = SqlAlchemyJobRepository(session_factory)
    result_repo = SqlAlchemyResultRepository(session_factory)

    pipeline_service = ExtractionPipelineService(
        blob_store=blob_store,
        document_reader=document_reader,
        decision_engine=dec_engine,
        extraction_engine=ext_engine,
        job_repo=job_repo,
        result_repo=result_repo,
        telemetry=telemetry,
        lease_seconds=cfg.worker_lease_seconds,
    )
    ingest_use_case = IngestDocumentUseCase(
        blob_store=blob_store,
        document_reader=document_reader,
        job_repo=job_repo,
        telemetry=telemetry,
        max_upload_bytes=cfg.max_upload_bytes,
    )
    request_extraction_use_case = RequestExtractionUseCase(
        job_repo=job_repo,
        telemetry=telemetry,
        settings=cfg,
    )
    inspect_job_use_case = InspectJobUseCase(
        job_repo=job_repo,
        result_repo=result_repo,
    )

    return AppContainer(
        settings=cfg,
        blob_store=blob_store,
        document_reader=document_reader,
        decision_engine=dec_engine,
        extraction_engine=ext_engine,
        job_repo=job_repo,
        result_repo=result_repo,
        telemetry=telemetry,
        pipeline_service=pipeline_service,
        ingest_use_case=ingest_use_case,
        request_extraction_use_case=request_extraction_use_case,
        inspect_job_use_case=inspect_job_use_case,
    )
