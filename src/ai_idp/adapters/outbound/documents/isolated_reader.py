"""Portable, killable document decoding with monitored memory and elapsed-time limits."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from ai_idp.application.ports.protocols import DocumentBlobStore
from ai_idp.domain.errors import (
    DocumentLimitExceededError,
    DomainError,
    MalformedDocumentError,
)
from ai_idp.domain.models import Document, DocumentUnit
from ai_idp.settings import Settings


class IsolatedDocumentReader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def supports(self, media_type: str) -> bool:
        from ai_idp.domain.media_types import SPREADSHEET_TYPES

        if media_type in SPREADSHEET_TYPES:
            return True
        return media_type in {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "image/tiff",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def normalize(
        self, document: Document, raw_bytes: bytes, blob_store: DocumentBlobStore
    ) -> list[DocumentUnit]:
        with tempfile.TemporaryDirectory(prefix="ai-idp-decode-") as temp:
            root = Path(temp)
            (root / "input.bin").write_bytes(raw_bytes)
            options = {
                name: getattr(self._settings, name)
                for name in (
                    "max_pdf_pages",
                    "pdf_render_dpi",
                    "max_image_pixels",
                    "max_docx_blocks",
                    "max_expanded_mib",
                    "max_image_frames",
                    "max_spreadsheet_sheets",
                    "max_spreadsheet_cells",
                    "max_document_units",
                    "spreadsheet_rows_per_unit",
                    "max_unit_text_characters",
                    "max_document_text_characters",
                    "max_formula_cells",
                    "max_formula_steps",
                )
            }
            (root / "request.json").write_text(
                json.dumps(
                    {
                        "document": document.model_dump(mode="json"),
                        "settings": options,
                        "lazy_pdf": bool(getattr(blob_store, "supports_lazy_pdf", False)),
                    }
                ),
                encoding="utf-8",
            )
            started = time.monotonic()
            with subprocess.Popen(
                [sys.executable, "-m", __name__, str(root)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ) as child:
                process = psutil.Process(child.pid)
                try:
                    while child.poll() is None:
                        if time.monotonic() - started > self._settings.document_timeout_seconds:
                            raise DocumentLimitExceededError(
                                "Document decoding time limit exceeded."
                            )
                        try:
                            rss = process.memory_info().rss
                        except psutil.NoSuchProcess:
                            break
                        if rss > self._settings.document_memory_mib * 1024 * 1024:
                            raise DocumentLimitExceededError(
                                "Document decoding memory limit exceeded."
                            )
                        try:
                            child.wait(timeout=0.05)
                        except subprocess.TimeoutExpired:
                            pass
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
            response_path = root / "response.json"
            if not response_path.exists():
                raise MalformedDocumentError("Document decoder terminated without a result.")
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if "error" in response:
                if response["error"] == "encrypted_document":
                    from ai_idp.domain.errors import EncryptedDocumentError

                    raise EncryptedDocumentError("Encrypted workbooks require a decrypted copy.")
                if response["error"] == "document_limit_exceeded":
                    raise DocumentLimitExceededError(response["message"])
                raise MalformedDocumentError("Document decoding failed; the input is malformed.")
            for artifact in (root / "artifacts").rglob("*"):
                if artifact.is_file():
                    blob_store.put_bytes(
                        artifact.relative_to(root / "artifacts").as_posix(), artifact.read_bytes()
                    )
            return [DocumentUnit.model_validate(unit) for unit in response["units"]]


def _main() -> None:
    from ai_idp.adapters.outbound.documents.composite_reader import CompositeDocumentReader
    from ai_idp.adapters.outbound.storage.local import LocalDocumentBlobStore

    root = Path(sys.argv[1])
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    settings = Settings(_env_file=None, **request["settings"])

    class BoundedArtifactStore(LocalDocumentBlobStore):
        written = 0
        supports_lazy_pdf = request.get("lazy_pdf", False)

        def put_bytes(self, key: str, content: bytes) -> str:
            self.written += len(content)
            if self.written > settings.max_expanded_bytes:
                raise DocumentLimitExceededError("Total decoded artifact size limit exceeded.")
            return super().put_bytes(key, content)

    try:
        units = CompositeDocumentReader.from_settings(settings).normalize(
            Document.model_validate(request["document"]),
            (root / "input.bin").read_bytes(),
            BoundedArtifactStore(root / "artifacts"),
        )
        response = {"units": [unit.model_dump(mode="json") for unit in units]}
    except DomainError as exc:
        response = {"error": exc.code, "message": exc.message}
    except Exception:
        response = {"error": "malformed_document", "message": "Document decoding failed."}
    (root / "response.json").write_text(json.dumps(response), encoding="utf-8")


if __name__ == "__main__":
    _main()
