from __future__ import annotations

from ai_idp.adapters.outbound.documents.docx_reader import MammothDocxDocumentReader
from ai_idp.adapters.outbound.documents.image_reader import PillowImageDocumentReader
from ai_idp.adapters.outbound.documents.pdf_reader import PyMuPdfDocumentReader
from ai_idp.adapters.outbound.documents.spreadsheet_reader import SpreadsheetDocumentReader
from ai_idp.application.ports.protocols import DocumentBlobStore, DocumentReader
from ai_idp.domain.errors import UnsupportedMediaTypeError
from ai_idp.domain.models import Document, DocumentUnit
from ai_idp.settings import Settings


class CompositeDocumentReader:
    """Dispatches document normalization to PDF, DOCX, or Image readers based on media type."""

    def __init__(self, readers: list[DocumentReader]) -> None:
        self._readers = readers
        self._settings: Settings | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> CompositeDocumentReader:
        result = cls(
            readers=[
                SpreadsheetDocumentReader(settings),
                PyMuPdfDocumentReader(
                    max_pages=settings.max_pdf_pages,
                    render_dpi=settings.pdf_render_dpi,
                    max_image_pixels=settings.max_image_pixels,
                    lazy_render=True,
                ),
                MammothDocxDocumentReader(
                    max_blocks=settings.max_docx_blocks,
                    max_expanded_bytes=settings.max_expanded_bytes,
                ),
                PillowImageDocumentReader(
                    max_frames=settings.max_image_frames,
                    max_image_pixels=settings.max_image_pixels,
                ),
            ]
        )
        result._settings = settings
        return result

    def supports(self, media_type: str) -> bool:
        return any(r.supports(media_type) for r in self._readers)

    def normalize(
        self,
        document: Document,
        raw_bytes: bytes,
        blob_store: DocumentBlobStore,
    ) -> list[DocumentUnit]:
        for reader in self._readers:
            if reader.supports(document.media_type):
                units = reader.normalize(document, raw_bytes, blob_store)
                if self._settings:
                    from ai_idp.domain.errors import DocumentLimitExceededError

                    if len(units) > self._settings.max_document_units:
                        raise DocumentLimitExceededError("Document source-unit limit exceeded.")
                    text_size = sum(
                        blob_store.get_size(u.native_text_ref) for u in units if u.native_text_ref
                    )
                    if text_size > self._settings.max_document_text_characters:
                        raise DocumentLimitExceededError("Document decoded-text limit exceeded.")
                return units
        raise UnsupportedMediaTypeError(
            f"No document reader registered for '{document.media_type}'."
        )
