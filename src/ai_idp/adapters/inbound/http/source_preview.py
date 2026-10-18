"""Source inspection without additional model calls or changes to verification."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ai_idp.domain.errors import DomainError

router = APIRouter()


class LocationRequest(BaseModel):
    quote: str = Field(default="", max_length=16000)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    artifact_sha256: str | None = None


def _unit(request: Request, document_id: str, unit_id: str):
    container = request.app.state.container
    _, units = container.inspect_job_use_case.get_document(document_id)
    unit = next((unit for unit in units if unit.unit_id == unit_id), None)
    if unit is None:
        raise DomainError("Source unit not found.", code="artifact_not_found", http_status=404)
    return container, unit


@router.get("/documents/{document_id}/units/{unit_id}/preview")
def preview(request: Request, response: Response, document_id: str, unit_id: str) -> dict:
    response.headers["Cache-Control"] = "no-store"
    container, unit = _unit(request, document_id, unit_id)
    text = container.blob_store.get_text(unit.native_text_ref) if unit.native_text_ref else ""
    html_ref = unit.metadata.get("semantic_html_ref")
    # This is generated allowlisted HTML, not the original DOCX HTML.
    html = container.blob_store.get_text(html_ref) if html_ref else None
    return {
        "unit_id": unit_id,
        "kind": unit.kind.value,
        "text": text,
        "html": html,
        "artifact_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "image_count": len(set(([unit.image_ref] if unit.image_ref else []) + unit.image_refs)),
        "warnings": unit.metadata.get("conversion_warnings", []),
    }


@router.post("/documents/{document_id}/units/{unit_id}/location")
def locate(
    request: Request, response: Response, document_id: str, unit_id: str, payload: LocationRequest
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    container, unit = _unit(request, document_id, unit_id)
    text = container.blob_store.get_text(unit.native_text_ref) if unit.native_text_ref else ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    base = {"unit_id": unit_id, "artifact_sha256": digest, "regions": []}
    if payload.artifact_sha256 and payload.artifact_sha256 != digest:
        return {**base, "status": "unavailable", "reason": "source_version_mismatch"}
    start, end = payload.start, payload.end
    if start is not None or end is not None:
        if start is None or end is None or not 0 <= start < end <= len(text):
            return {**base, "status": "unavailable", "reason": "invalid_span"}
        if payload.quote and text[start:end] != payload.quote:
            return {**base, "status": "unit_only", "reason": "span_quote_mismatch"}
    elif payload.quote:
        start = text.find(payload.quote)
        if start < 0:
            return {**base, "status": "unit_only", "reason": "quote_not_found"}
        if text.find(payload.quote, start + 1) >= 0:
            return {**base, "status": "ambiguous", "reason": "repeated_quote"}
        end = start + len(payload.quote)
    else:
        return {**base, "status": "unit_only", "reason": "no_text_anchor"}
    # A location lookup must not turn 100 inside 1000 into a precise citation.
    token = text[start:end]
    if (token[0].isalnum() and start > 0 and text[start - 1].isalnum()) or (
        token[-1].isalnum() and end < len(text) and text[end].isalnum()
    ):
        return {**base, "status": "unit_only", "reason": "partial_token"}
    geometry_ref = unit.metadata.get("text_geometry_ref")
    if unit.kind.value == "spreadsheet_range":
        cells = [
            c["cell"]
            for c in unit.metadata.get("cell_spans", [])
            if c["start"] <= start < end <= c["end"]
        ]
        if len(cells) == 1:
            return {
                **base,
                "status": "exact",
                "method": "spreadsheet_cell",
                "cell": cells[0],
                "sheet_name": unit.source_locator["sheet_name"],
                "start": start,
                "end": end,
            }
    if not geometry_ref:
        return {**base, "status": "unit_only", "start": start, "end": end}
    geometry = json.loads(container.blob_store.get_text(geometry_ref))
    if geometry["text_sha256"] != digest:
        return {**base, "status": "unavailable", "reason": "geometry_version_mismatch"}
    words = [w for w in geometry["words"] if w["start"] < end and w["end"] > start]
    covered = set()
    for word in words:
        covered.update(range(max(start, word["start"]), min(end, word["end"])))
    complete = all(text[index].isspace() or index in covered for index in range(start, end))
    regions = [w["rect"] for w in words] if complete else []
    return {
        **base,
        "status": "exact" if regions else "unit_only",
        "method": "native_text",
        "coordinate_space": "normalized_display_image_top_left",
        "image_index": 0,
        "image_sha256": geometry["image_sha256"],
        "start": start,
        "end": end,
        "regions": regions,
    }
