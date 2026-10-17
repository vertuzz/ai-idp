from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, FastAPI, File, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from ai_idp.adapters.inbound.http.dependencies import AppContainer, build_container
from ai_idp.adapters.inbound.http.schemas import (
    CreateExtractionRequest,
    CreateExtractionResponse,
    DecisionItemResponse,
    DecisionsListResponse,
    DocumentDetailResponse,
    DocumentUploadResponse,
    EvidenceItemResponse,
    ExtractionResultResponse,
    FieldResultItemResponse,
    JobLinks,
    JobProgressResponse,
    JobStatusResponse,
    JobUsageResponse,
)
from ai_idp.domain.errors import DomainError


def create_app(container: AppContainer | None = None) -> FastAPI:
    app = FastAPI(
        title="AI-IDP API",
        version="0.1.0",
        description="Evaluation-first, AI-directed intelligent document processing",
    )
    app.state.container = container or build_container()

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error_id": f"err_{uuid.uuid4().hex[:10]}",
                "code": exc.code,
                "message": exc.message,
            },
        )

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready(request: Request) -> JSONResponse:
        c: AppContainer = request.app.state.container
        db_ok = c.job_repo.check_health()
        storage_ok = c.blob_store.check_health()
        status_code = 200 if (db_ok and storage_ok) else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if status_code == 200 else "degraded",
                "database": "ok" if db_ok else "unreachable",
                "storage": "ok" if storage_ok else "unavailable",
            },
        )

    v1 = APIRouter(prefix="/v1")

    @v1.post("/documents", status_code=201, response_model=DocumentUploadResponse)
    async def upload_document(
        request: Request,
        file: Annotated[UploadFile, File(...)],
    ) -> DocumentUploadResponse:
        c: AppContainer = request.app.state.container
        raw_bytes = await file.read()
        doc = c.ingest_use_case.execute(
            raw_bytes=raw_bytes,
            filename=file.filename or "upload.bin",
            declared_media_type=file.content_type,
            eager_normalize=True,
        )
        return DocumentUploadResponse(
            document_id=doc.document_id,
            filename=doc.filename,
            media_type=doc.media_type,
            sha256=doc.sha256,
            status=doc.status.value,
        )

    @v1.get("/documents/{document_id}", response_model=DocumentDetailResponse)
    async def get_document(request: Request, document_id: str) -> DocumentDetailResponse:
        c: AppContainer = request.app.state.container
        doc, units = c.inspect_job_use_case.get_document(document_id)
        return DocumentDetailResponse(
            document_id=doc.document_id,
            filename=doc.filename,
            media_type=doc.media_type,
            sha256=doc.sha256,
            bytes=doc.bytes_size,
            status=doc.status.value,
            units_count=len(units),
            created_at=doc.created_at,
        )

    @v1.post("/extractions", status_code=202, response_model=CreateExtractionResponse)
    async def create_extraction(
        request: Request,
        payload: CreateExtractionRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        run_inline: Annotated[bool, Query()] = False,
    ) -> CreateExtractionResponse:
        c: AppContainer = request.app.state.container
        job = c.request_extraction_use_case.execute(
            document_id=payload.document_id,
            schema_json=payload.schema_def,
            instructions=payload.instructions,
            model_profile=payload.model_profile,
            idempotency_key=idempotency_key,
        )
        if run_inline and job.status.value == "pending":
            await c.pipeline_service.execute_job(job.job_id)
            job = c.inspect_job_use_case.get_job(job.job_id)
            c.job_repo.complete_queue_item(job.job_id, job.status)

        return CreateExtractionResponse(
            job_id=job.job_id,
            document_id=job.document_id,
            status=job.status.value,
            links=JobLinks(
                self=f"/v1/extractions/{job.job_id}",
                result=f"/v1/extractions/{job.job_id}/result",
            ),
        )

    @v1.get("/extractions/{job_id}", response_model=JobStatusResponse)
    async def get_extraction_job(request: Request, job_id: str) -> JobStatusResponse:
        c: AppContainer = request.app.state.container
        job = c.inspect_job_use_case.get_job(job_id)
        return JobStatusResponse(
            job_id=job.job_id,
            document_id=job.document_id,
            status=job.status.value,
            stage=job.stage.value,
            progress=JobProgressResponse(
                units_total=job.progress.units_total,
                units_scored=job.progress.units_scored,
                fields_completed=job.progress.fields_completed,
                fields_total=job.progress.fields_total,
            ),
            usage=JobUsageResponse(
                llm_calls=job.usage.llm_calls,
                estimated_cost_usd=job.usage.estimated_cost_usd,
            ),
            last_error=job.last_error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @v1.get("/extractions/{job_id}/result", response_model=ExtractionResultResponse)
    async def get_extraction_result(request: Request, job_id: str) -> ExtractionResultResponse:
        c: AppContainer = request.app.state.container
        result = c.inspect_job_use_case.get_result(job_id)
        fields_resp = {
            f_path: FieldResultItemResponse(
                status=fv.status.value,
                verification=fv.verification.value if fv.verification else None,
                raw_probabilities=fv.raw_probabilities,
                sources=[
                    EvidenceItemResponse(
                        unit_id=ev.unit_id,
                        locator=ev.locator,
                        quote=ev.quote,
                        bounding_box=ev.bounding_box,
                    )
                    for ev in fv.sources
                ],
                attempt_count=fv.attempt_count,
                unresolved_reason=fv.unresolved_reason,
            )
            for f_path, fv in result.fields.items()
        }
        return ExtractionResultResponse(
            job_id=result.job_id,
            status=result.status.value,
            data=result.data,
            schema_valid=result.schema_valid,
            fields=fields_resp,
            unresolved_fields=result.unresolved_fields,
            usage=JobUsageResponse(
                llm_calls=result.usage.llm_calls,
                estimated_cost_usd=result.usage.estimated_cost_usd,
            ),
        )

    @v1.get("/extractions/{job_id}/decisions", response_model=DecisionsListResponse)
    async def get_extraction_decisions(request: Request, job_id: str) -> DecisionsListResponse:
        c: AppContainer = request.app.state.container
        decisions = c.inspect_job_use_case.list_decisions(job_id)
        return DecisionsListResponse(
            job_id=job_id,
            decisions=[
                DecisionItemResponse(
                    decision_id=d.decision_id,
                    unit_id=d.unit_id,
                    field_path=d.field_path,
                    kind=d.kind.value,
                    model_id=d.model_id,
                    version=d.version,
                    scores=d.scores,
                    selected=d.selected,
                    latency_ms=d.latency_ms,
                    created_at=d.created_at,
                )
                for d in decisions
            ],
        )

    @v1.post("/extractions/{job_id}/cancel", response_model=JobStatusResponse)
    async def cancel_extraction_job(request: Request, job_id: str) -> JobStatusResponse:
        c: AppContainer = request.app.state.container
        job = c.inspect_job_use_case.cancel_job(job_id)
        return JobStatusResponse(
            job_id=job.job_id,
            document_id=job.document_id,
            status=job.status.value,
            stage=job.stage.value,
            progress=JobProgressResponse(
                units_total=job.progress.units_total,
                units_scored=job.progress.units_scored,
                fields_completed=job.progress.fields_completed,
                fields_total=job.progress.fields_total,
            ),
            usage=JobUsageResponse(
                llm_calls=job.usage.llm_calls,
                estimated_cost_usd=job.usage.estimated_cost_usd,
            ),
            last_error=job.last_error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    app.include_router(v1)
    return app
