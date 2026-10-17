from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

REDACTED_ATTRIBUTE_KEYS = frozenset(
    {"api_key", "authorization", "raw_text", "native_text", "image_bytes", "prompt"}
)


def _sanitize_attributes(attributes: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    if not attributes:
        return {}
    safe: dict[str, str | int | float | bool] = {}
    for k, v in attributes.items():
        if k.lower() in REDACTED_ATTRIBUTE_KEYS:
            continue
        if isinstance(v, (bool, int, float)):
            safe[k] = v
        elif v is not None:
            safe[k] = str(v)[:256]
    return safe


class RotatingJsonlSpanExporter(SpanExporter):
    """Exports OpenTelemetry spans to a local rotating JSONL file."""

    def __init__(
        self, directory: Path, max_bytes: int = 10 * 1024 * 1024, retained_files: int = 20
    ) -> None:
        self._dir = directory.resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._current_file = self._dir / f"spans-{os.getpid()}.jsonl"
        self._retained_files = retained_files

    def export(self, spans: tuple[ReadableSpan, ...] | list[ReadableSpan]) -> SpanExportResult:
        with self._lock:
            try:
                if (
                    self._current_file.exists()
                    and self._current_file.stat().st_size >= self._max_bytes
                ):
                    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                    rotated = self._dir / f"spans-archive-{ts}-{uuid.uuid4().hex[:8]}.jsonl"
                    self._current_file.replace(rotated)
                    archives = sorted(
                        self._dir.glob("spans-archive-*.jsonl"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    for old in archives[self._retained_files :]:
                        old.unlink(missing_ok=True)
                with self._current_file.open("a", encoding="utf-8") as fh:
                    for span in spans:
                        ctx = span.get_span_context()
                        payload = {
                            "timestamp": datetime.now(UTC).isoformat(),
                            "name": span.name,
                            "trace_id": f"{ctx.trace_id:032x}" if ctx else None,
                            "span_id": f"{ctx.span_id:016x}" if ctx else None,
                            "start_time_ns": span.start_time,
                            "end_time_ns": span.end_time,
                            "duration_ms": (
                                round((span.end_time - span.start_time) / 1_000_000, 2)
                                if span.start_time and span.end_time
                                else None
                            ),
                            "status": span.status.status_code.name if span.status else "UNSET",
                            "attributes": dict(span.attributes or {}),
                            "events": [
                                {
                                    "name": ev.name,
                                    "attributes": dict(ev.attributes or {}),
                                }
                                for ev in span.events
                            ],
                        }
                        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
                return SpanExportResult.SUCCESS
            except OSError:
                return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        return None


class OpenTelemetryJsonlAdapter:
    """TelemetryPort implementation backed by OpenTelemetry SDK and local JSONL exporter."""

    def __init__(
        self,
        telemetry_dir: Path,
        service_name: str = "ai-idp",
        *,
        max_bytes: int = 10 * 1024 * 1024,
        retained_files: int = 20,
    ) -> None:
        self._dir = telemetry_dir
        resource = Resource.create({"service.name": service_name})
        self._provider = TracerProvider(resource=resource)
        self._exporter = RotatingJsonlSpanExporter(telemetry_dir, max_bytes, retained_files)
        self._provider.add_span_processor(SimpleSpanProcessor(self._exporter))
        self._tracer: trace.Tracer = self._provider.get_tracer(service_name)

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
        safe_attrs = _sanitize_attributes(attributes)
        with self._tracer.start_as_current_span(
            name, attributes=safe_attrs, record_exception=False, set_status_on_exception=False
        ) as current_span:
            try:
                yield current_span
            except BaseException as exc:
                code = getattr(exc, "code", "internal_error")
                current_span.set_status(Status(StatusCode.ERROR, code))
                current_span.add_event("error", {"error_type": type(exc).__name__, "code": code})
                raise

    def record_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        safe_attrs = _sanitize_attributes(attributes)
        current = trace.get_current_span()
        if current and current.is_recording():
            current.add_event(name, attributes=safe_attrs)
        else:
            with self._tracer.start_as_current_span(f"event.{name}", attributes=safe_attrs):
                pass
