from __future__ import annotations

import asyncio
import secrets
import tempfile
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, File, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ai_idp.adapters.inbound.http.body_limit import BodyLimitMiddleware, RequestBodyTooLarge
from ai_idp.adapters.inbound.http.dependencies import AppContainer, build_container
from ai_idp.adapters.inbound.http.result_pages import router as result_pages_router
from ai_idp.adapters.inbound.http.schemas import (
    CreateExtractionRequest,
    CreateExtractionResponse,
    DecisionItemResponse,
    DecisionsListResponse,
    DocumentDetailResponse,
    DocumentUploadResponse,
    EvidenceItemResponse,
    ExtractionResultResponse,
    FieldAttemptResponse,
    FieldResultItemResponse,
    JobLinks,
    JobProgressResponse,
    JobStatusResponse,
    JobUsageResponse,
)
from ai_idp.adapters.inbound.http.source_preview import router as source_preview_router
from ai_idp.adapters.inbound.http.telemetry import RequestTelemetryMiddleware
from ai_idp.domain.errors import AuthenticationError, DomainError, UploadTooLargeError


def create_app(
    container: AppContainer | None = None,
    *,
    v1_dependencies: Sequence[Any] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="AI-IDP API",
        version="0.1.0",
        description="Evaluation-first, AI-directed intelligent document processing",
    )
    app.state.container = container or build_container()
    app.add_middleware(RequestTelemetryMiddleware, telemetry=app.state.container.telemetry)
    app.add_middleware(
        BodyLimitMiddleware, max_bytes=app.state.container.settings.max_upload_bytes + 64 * 1024
    )
    ingestion_slots = asyncio.Semaphore(app.state.container.settings.max_concurrent_jobs)

    async def ingestion_slot():
        async with ingestion_slots:
            yield

    async def require_api_key(
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        expected = request.app.state.container.settings.api_key
        if not expected:
            return
        token = ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        elif x_api_key:
            token = x_api_key.strip()
        if not token or not secrets.compare_digest(token, expected):
            raise AuthenticationError("Invalid or missing API key.")

    @app.exception_handler(RequestBodyTooLarge)
    async def handle_oversized_body(_request: Request, _exc: RequestBodyTooLarge) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "error_id": f"err_{uuid.uuid4().hex[:10]}",
                "code": "upload_too_large",
                "message": "Request body exceeds the configured size limit.",
            },
        )

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

    router_dependencies = (
        list(v1_dependencies) if v1_dependencies is not None else [Depends(require_api_key)]
    )
    v1 = APIRouter(prefix="/v1", dependencies=router_dependencies)
    v1.include_router(source_preview_router)
    v1.include_router(result_pages_router)

    @v1.post("/documents", status_code=201, response_model=DocumentUploadResponse)
    async def upload_document(
        request: Request,
        file: Annotated[UploadFile, File(...)],
        _slot: None = Depends(ingestion_slot),
    ) -> DocumentUploadResponse:
        c: AppContainer = request.app.state.container
        try:
            with tempfile.TemporaryFile() as upload:
                received = 0
                while chunk := await file.read(1024 * 1024):
                    received += len(chunk)
                    if received > c.settings.max_upload_bytes:
                        raise UploadTooLargeError("Upload exceeds the configured size limit.")
                    upload.write(chunk)
                upload.seek(0)
                raw_bytes = upload.read()
            doc = await asyncio.to_thread(
                c.ingest_use_case.execute,
                raw_bytes=raw_bytes,
                filename=file.filename or "upload.bin",
                declared_media_type=file.content_type,
                eager_normalize=True,
            )
        finally:
            await file.close()
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
            conversion_warnings=list(
                dict.fromkeys(
                    warning for u in units for warning in u.metadata.get("conversion_warnings", [])
                )
            ),
            created_at=doc.created_at,
        )

    @v1.get("/documents/{document_id}/content")
    async def get_original(request: Request, document_id: str) -> Response:
        c: AppContainer = request.app.state.container
        document, _ = c.inspect_job_use_case.get_document(document_id)
        return Response(
            c.blob_store.get_bytes(document.storage_key),
            media_type=document.media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "attachment",
            },
        )

    @v1.get("/documents/{document_id}/units")
    async def list_units(
        request: Request,
        document_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> dict:
        c: AppContainer = request.app.state.container
        _, units = c.inspect_job_use_case.get_document(document_id)
        return {
            "document_id": document_id,
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit if offset + limit < len(units) else None,
            "units": [
                {
                    "unit_id": u.unit_id,
                    "kind": u.kind.value,
                    "locator": u.source_locator,
                    "available_modalities": [m.value for m in u.available_modalities],
                    "conversion_warnings": u.metadata.get("conversion_warnings", []),
                    "image_count": len(set(([u.image_ref] if u.image_ref else []) + u.image_refs)),
                    "has_text": bool(u.native_text_ref),
                }
                for u in units[offset : offset + limit]
            ],
        }

    @v1.get("/documents/{document_id}/units/{unit_id}/text")
    async def get_unit_text(request: Request, document_id: str, unit_id: str) -> Response:
        c: AppContainer = request.app.state.container
        _, units = c.inspect_job_use_case.get_document(document_id)
        unit = next((u for u in units if u.unit_id == unit_id), None)
        if unit is None or not unit.native_text_ref:
            raise DomainError(
                "Source text is unavailable.", code="artifact_not_found", http_status=404
            )
        return Response(
            c.blob_store.get_text(unit.native_text_ref),
            media_type="text/plain",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @v1.get("/documents/{document_id}/units/{unit_id}/images/{image_index}")
    async def get_unit_image(
        request: Request,
        document_id: str,
        unit_id: str,
        image_index: int,
    ) -> Response:
        c: AppContainer = request.app.state.container
        _, units = c.inspect_job_use_case.get_document(document_id)
        unit = next((u for u in units if u.unit_id == unit_id), None)
        refs = list(
            dict.fromkeys(
                ([unit.image_ref] if unit and unit.image_ref else [])
                + (unit.image_refs if unit else [])
            )
        )
        if image_index < 0 or image_index >= len(refs):
            raise DomainError(
                "Source image is unavailable.", code="artifact_not_found", http_status=404
            )
        ref = refs[image_index]
        media_type = "image/jpeg" if ref.endswith((".jpg", ".jpeg")) else "image/png"
        return Response(
            c.blob_store.get_bytes(ref),
            media_type=media_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
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
                tokens_in=job.usage.tokens_in,
                tokens_out=job.usage.tokens_out,
                total_latency_ms=job.usage.total_latency_ms,
            ),
            last_error=job.last_error,
            configuration=job.configuration.model_dump(mode="json"),
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @v1.get("/extractions/{job_id}/result", response_model=ExtractionResultResponse)
    async def get_extraction_result(request: Request, job_id: str) -> ExtractionResultResponse:
        c: AppContainer = request.app.state.container
        c.inspect_job_use_case.get_job(job_id)
        view = c.result_repo.load_step(job_id, "view:manifest")
        if view and (
            view["field_count"] > 1000
            or any(collection["total_items"] > 100 for collection in view["collections"])
        ):
            raise DomainError(
                f"Use /v1/extractions/{job_id}/result/manifest and collection pages, "
                "or /result/export for the complete JSON.",
                code="result_requires_pagination",
                http_status=413,
            )
        result = c.inspect_job_use_case.get_result(job_id)
        fields_resp = {
            f_path: FieldResultItemResponse(
                status=fv.status.value,
                verification=fv.verification.value if fv.verification else None,
                raw_value=fv.raw_value,
                normalization_method=fv.normalization_method,
                qualifiers=list(fv.qualifiers),
                unit=fv.unit,
                raw_probabilities=fv.raw_probabilities,
                sources=[
                    EvidenceItemResponse(
                        unit_id=ev.unit_id,
                        locator=ev.locator,
                        quote=ev.quote,
                        raw_value=ev.raw_value,
                        bounding_box=ev.bounding_box,
                        text_span=ev.text_span.model_dump(mode="json") if ev.text_span else None,
                    )
                    for ev in fv.sources
                ],
                attempt_count=fv.attempt_count,
                unresolved_reason=fv.unresolved_reason,
                attempts=[
                    FieldAttemptResponse.model_validate(a.model_dump(mode="json"))
                    for a in fv.attempts
                ],
                check_results=[c.model_dump(mode="json") for c in fv.check_results],
            )
            for f_path, fv in result.fields.items()
        }
        return ExtractionResultResponse(
            job_id=result.job_id,
            status=result.status.value,
            data=result.data,
            schema_valid=result.schema_valid,
            schema_errors=result.schema_errors,
            fields=fields_resp,
            unresolved_fields=result.unresolved_fields,
            usage=JobUsageResponse(
                llm_calls=result.usage.llm_calls,
                estimated_cost_usd=result.usage.estimated_cost_usd,
                tokens_in=result.usage.tokens_in,
                tokens_out=result.usage.tokens_out,
                total_latency_ms=result.usage.total_latency_ms,
            ),
        )

    @v1.get("/extractions/{job_id}/decisions", response_model=DecisionsListResponse)
    async def get_extraction_decisions(
        request: Request,
        job_id: str,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> DecisionsListResponse:
        c: AppContainer = request.app.state.container
        decisions = c.inspect_job_use_case.list_decisions(job_id, offset=offset, limit=limit + 1)
        return DecisionsListResponse(
            job_id=job_id,
            offset=offset,
            limit=limit,
            next_offset=offset + limit if len(decisions) > limit else None,
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
                for d in decisions[:limit]
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
                tokens_in=job.usage.tokens_in,
                tokens_out=job.usage.tokens_out,
                total_latency_ms=job.usage.total_latency_ms,
            ),
            last_error=job.last_error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    app.include_router(v1)
    return app
