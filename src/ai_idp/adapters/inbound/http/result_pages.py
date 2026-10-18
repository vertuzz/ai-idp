"""Authorized, database-paged result inspection and incremental full JSON export."""

from __future__ import annotations

import base64
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ai_idp.application.services.result_views import collection_key
from ai_idp.domain.errors import DomainError

router = APIRouter()


def _container(request: Request, job_id: str):
    container = request.app.state.container
    job = container.inspect_job_use_case.get_job(job_id)
    return container, job


def _manifest(container: Any, job_id: str) -> dict:
    value = container.result_repo.load_step(job_id, "view:manifest")
    job = container.inspect_job_use_case.get_job(job_id)
    if not value or job.status.value not in {"completed", "completed_with_unresolved"}:
        raise DomainError(
            "The final result is not ready; inspect saved provisional parts.",
            code="job_not_completed",
            http_status=409,
        )
    return value


def _cursor(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _decode(token: str, job_id: str, path: str) -> dict:
    try:
        value = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        if value["job"] != job_id or value["path"] != path or value["revision"] != "final-v1":
            raise ValueError()
        if not isinstance(value["page"], int) or value["page"] < 0:
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise DomainError(
            "Invalid or stale result cursor.", code="invalid_cursor", http_status=409
        ) from None


@router.get("/extractions/{job_id}/result/manifest")
def manifest(request: Request, job_id: str):
    container, _ = _container(request, job_id)
    return _manifest(container, job_id)


@router.get("/extractions/{job_id}/result/collections")
def collection(
    request: Request,
    job_id: str,
    path: str,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
):
    container, _ = _container(request, job_id)
    info = _manifest(container, job_id)
    descriptor = next((c for c in info["collections"] if c["path"] == path), None)
    if descriptor is None:
        raise DomainError("Collection not found.", code="collection_not_found", http_status=404)
    index = _decode(cursor, job_id, path)["page"] if cursor else 0
    page = container.result_repo.load_step(job_id, collection_key(path) + f"{index:06d}")
    if page is None and (descriptor["pages"] or index):
        raise DomainError("Result page not found.", code="page_not_found", http_status=404)
    page = dict(page or {"path": path, "start_index": 0, "items": [], "fields": {}})
    next_page = page.pop("next_page", None)
    page.update(
        total_items=descriptor["total_items"],
        revision=info["revision"],
        next_cursor=_cursor(
            {"job": job_id, "path": path, "revision": info["revision"], "page": next_page}
        )
        if next_page is not None
        else None,
    )
    return page


@router.get("/extractions/{job_id}/result/parts")
def parts(
    request: Request, job_id: str, after: str = "", limit: Annotated[int, Query(ge=1, le=20)] = 10
):
    container, job = _container(request, job_id)
    if after and not after.startswith("partial:"):
        raise DomainError("Invalid part cursor.", code="invalid_cursor", http_status=422)
    rows = container.result_repo.list_steps(job_id, "partial:", after=after, limit=limit)
    # Size is bounded independently from the row count.
    selected, size = [], 0
    for key, payload in rows:
        length = len(json.dumps(payload).encode())
        if selected and size + length > container.settings.result_page_bytes:
            break
        if length > container.settings.result_page_bytes:
            raise DomainError(
                "Part exceeds the preview byte limit.", code="part_too_large", http_status=413
            )
        selected.append({"part_id": key, **payload})
        size += length
    return {
        "job_id": job_id,
        "complete": job.status.value in {"completed", "completed_with_unresolved"},
        "status": job.status.value,
        "parts": selected,
        "next_cursor": selected[-1]["part_id"] if selected else after or None,
    }


@router.get("/extractions/{job_id}/result/export")
def export(request: Request, job_id: str):
    container, _ = _container(request, job_id)
    info = _manifest(container, job_id)
    paths = {c["path"]: c for c in info["collections"]}

    def emit(value: Any, path: str = ""):
        if path in paths:
            yield "["
            first = True
            for index in range(paths[path]["pages"]):
                page = container.result_repo.load_step(
                    job_id, collection_key(path) + f"{index:06d}"
                )
                for item in page["items"]:
                    if not first:
                        yield ","
                    first = False
                    yield json.dumps(item, ensure_ascii=True)
            yield "]"
        elif isinstance(value, dict):
            from ai_idp.domain.field_paths import escape_segment

            yield "{"
            for index, (key, item) in enumerate(value.items()):
                if index:
                    yield ","
                yield json.dumps(key) + ":"
                yield from emit(item, path + "/" + escape_segment(key))
            yield "}"
        else:
            yield json.dumps(value, ensure_ascii=True)

    return StreamingResponse(
        emit(info["data"]),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}.json"',
            "Cache-Control": "no-store",
        },
    )
