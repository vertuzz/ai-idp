from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from ai_idp.domain.errors import DomainError

router = APIRouter()


class SuggestSchemaRequest(BaseModel):
    document_ids: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        min_length=1, max_length=5
    )
    max_cost_usd: float | None = Field(default=None, gt=0)


@router.post("/schema-suggestions", status_code=202)
def suggest_schema(
    request: Request,
    payload: SuggestSchemaRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
):
    service = request.app.state.container.suggestion_service
    scope = getattr(request.state, "suggestion_scope", "self-hosted")
    if idempotency_key:
        idempotency_key = hashlib.sha256(f"{scope}:{idempotency_key}".encode()).hexdigest()
    job = service.submit(
        payload.document_ids, key=idempotency_key, max_cost_usd=payload.max_cost_usd
    )
    hook = getattr(request.app.state, "on_schema_suggestion_created", None)
    if hook:
        hook(request, job)
    return service.public_view(job)


@router.get("/schema-suggestions/{job_id}")
def get_suggestion(request: Request, job_id: str):
    service = request.app.state.container.suggestion_service
    job = service.repo.get(job_id)
    if job is None:
        raise DomainError("Schema suggestion was not found.", code="not_found", http_status=404)
    return service.public_view(job)


@router.post("/schema-suggestions/{job_id}/cancel")
def cancel_suggestion(request: Request, job_id: str):
    service = request.app.state.container.suggestion_service
    if service.repo.get(job_id) is None:
        raise DomainError("Schema suggestion was not found.", code="not_found", http_status=404)
    service.repo.cancel(job_id)
    return service.public_view(service.repo.get(job_id))
