from __future__ import annotations

import hashlib
import io
import uuid
import zipfile

from ai_idp.application.ports.protocols import (
    DocumentBlobStore,
    DocumentReader,
    JobRepository,
    TelemetryPort,
)
from ai_idp.domain.enums import DocumentStatus
from ai_idp.domain.errors import UnsupportedMediaTypeError, UploadTooLargeError
from ai_idp.domain.models import Document

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def detect_media_type(
    raw_bytes: bytes, declared_media_type: str | None = None, filename: str = ""
) -> str:
    """Detect and validate supported media types from file magic bytes."""
    if raw_bytes.startswith(b"%PDF-"):
        return "application/pdf"
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if raw_bytes.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                from ai_idp.domain.media_types import (
                    XLSB_MIME,
                    XLSM_MIME,
                    XLSX_MIME,
                )

                if "xl/workbook.bin" in zf.namelist():
                    return XLSB_MIME
                if "xl/workbook.xml" in zf.namelist():
                    return XLSM_MIME if "xl/vbaProject.bin" in zf.namelist() else XLSX_MIME
                if "word/document.xml" in zf.namelist():
                    return DOCX_MIME
        except zipfile.BadZipFile as exc:
            raise UnsupportedMediaTypeError(
                "Uploaded ZIP archive is corrupted or not a valid DOCX."
            ) from exc
    if raw_bytes.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        # OLE may contain a BIFF workbook or an encrypted OOXML package. The isolated
        # reader distinguishes them without opening Office or executing active content.
        return "application/vnd.ms-excel"
    raise UnsupportedMediaTypeError(
        f"Unsupported or unrecognized file format "
        f"(declared='{declared_media_type}', filename='{filename}'). "
        "Supported types: PDF, DOCX, PNG, JPEG, TIFF, XLSX, XLSM, XLS, XLSB."
    )


class IngestDocumentUseCase:
    """Ingests, validates, stores, and optionally normalizes an uploaded document."""

    def __init__(
        self,
        *,
        blob_store: DocumentBlobStore,
        document_reader: DocumentReader,
        job_repo: JobRepository,
        telemetry: TelemetryPort,
        max_upload_bytes: int,
    ) -> None:
        self._blob_store = blob_store
        self._document_reader = document_reader
        self._job_repo = job_repo
        self._telemetry = telemetry
        self._max_upload_bytes = max_upload_bytes

    def execute(
        self,
        *,
        raw_bytes: bytes,
        filename: str,
        declared_media_type: str | None = None,
        eager_normalize: bool = True,
    ) -> Document:
        if len(raw_bytes) == 0:
            raise UnsupportedMediaTypeError("Uploaded file is empty.")
        if len(raw_bytes) > self._max_upload_bytes:
            raise UploadTooLargeError(
                f"Upload size ({len(raw_bytes)} bytes) exceeds maximum "
                f"allowed ({self._max_upload_bytes} bytes)."
            )

        media_type = detect_media_type(raw_bytes, declared_media_type, filename)
        if not self._document_reader.supports(media_type):
            raise UnsupportedMediaTypeError(f"Media type '{media_type}' is not supported.")

        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        safe_display_name = (filename or "document").replace("\\", "/").split("/")[-1][:255]
        storage_key = f"originals/{doc_id}.bin"

        with self._telemetry.span(
            "use_case.ingest_document",
            {"document_id": doc_id, "media_type": media_type, "bytes": len(raw_bytes)},
        ):
            self._blob_store.put_bytes(storage_key, raw_bytes)
            document = Document(
                document_id=doc_id,
                filename=safe_display_name,
                media_type=media_type,
                sha256=sha256,
                bytes_size=len(raw_bytes),
                storage_key=storage_key,
                status=DocumentStatus.STORED,
            )
            self._job_repo.save_document(document)

            if eager_normalize:
                try:
                    units = self._document_reader.normalize(document, raw_bytes, self._blob_store)
                except Exception:
                    document.status = DocumentStatus.FAILED
                    self._job_repo.save_document(document)
                    self._blob_store.delete(storage_key)
                    raise
                self._job_repo.save_units(doc_id, units)
                document.status = DocumentStatus.PREPARED
                self._job_repo.save_document(document)

            return document
