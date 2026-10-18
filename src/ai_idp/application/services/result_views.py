"""Persist bounded result projections once; HTTP pages never materialize the full result."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from ai_idp.domain.errors import DocumentLimitExceededError
from ai_idp.domain.field_paths import escape_segment


def collection_key(path: str) -> str:
    return "view:collection:" + hashlib.sha256(path.encode()).hexdigest()[:24] + ":"


def publish_result_view(repo: Any, result: Any, *, page_bytes: int = 1024 * 1024) -> None:
    collections = []
    fields = result.fields

    def diagnostic(path: str) -> dict[str, Any]:
        field = fields.get(path)
        if not field:
            return {}
        value = field.model_dump(mode="json")
        # Values are delivered once through data; attempts remain available on small
        # diagnostics. Large container histories cannot expand an HTTP page without bound.
        value.pop("value", None)
        value["attempts"] = []
        return value

    def visit(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            return {k: visit(v, path + "/" + escape_segment(k)) for k, v in value.items()}
        if not isinstance(value, list):
            return value
        prefix = collection_key(path)
        indexed_fields: dict[int, list[str]] = {}
        for pointer in fields:
            if pointer.startswith(path + "/"):
                segment = pointer[len(path) + 1 :].split("/", 1)[0]
                if segment.isdigit():
                    indexed_fields.setdefault(int(segment), []).append(pointer)
        pages = []
        start = 0
        while start < len(value):
            stop = min(start + 100, len(value))
            while True:
                page_fields = {
                    p: diagnostic(p) for i in range(start, stop) for p in indexed_fields.get(i, [])
                }
                page = {
                    "path": path,
                    "start_index": start,
                    "items": value[start:stop],
                    "fields": page_fields,
                    "next_page": len(pages) + 1 if stop < len(value) else None,
                }
                if len(json.dumps(page, ensure_ascii=True).encode()) <= page_bytes:
                    break
                if stop - start <= 1:
                    raise DocumentLimitExceededError(
                        "A result record exceeds the delivery page limit."
                    )
                stop = start + max(1, (stop - start) // 2)
            repo.save_step(result.job_id, prefix + f"{len(pages):06d}", page, None)
            pages.append({"start_index": start, "count": stop - start})
            start = stop
        parent = fields.get(path)
        collections.append(
            {
                "path": path,
                "total_items": len(value),
                "pages": len(pages),
                "status": parent.status.value if parent else "unresolved",
                "unresolved_reason": parent.unresolved_reason if parent else None,
            }
        )
        return []

    skeleton = visit(copy.deepcopy(result.data), "")
    collection_paths = [c["path"] for c in collections]
    scalar_fields = {
        p: diagnostic(p)
        for p in fields
        if not any(p == c or p.startswith(c + "/") for c in collection_paths)
    }
    manifest = {
        "job_id": result.job_id,
        "revision": "final-v1",
        "complete": True,
        "status": result.status.value,
        "data": skeleton,
        "collections": collections,
        "fields": scalar_fields,
        "field_count": len(fields),
        "schema_valid": result.schema_valid,
        "schema_errors": result.schema_errors[:100],
        "unresolved_count": len(result.unresolved_fields),
        "usage": result.usage.model_dump(),
    }
    if len(json.dumps(manifest, ensure_ascii=True).encode()) > page_bytes:
        raise DocumentLimitExceededError("Scalar result exceeds the delivery page limit.")
    repo.save_step(result.job_id, "view:manifest", manifest, None)
