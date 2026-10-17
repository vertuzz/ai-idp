from __future__ import annotations

from ai_idp.adapters.outbound.documents.docx_reader import MammothDocxDocumentReader
from ai_idp.adapters.outbound.documents.image_reader import PillowImageDocumentReader
from ai_idp.adapters.outbound.documents.pdf_reader import PyMuPdfDocumentReader
from ai_idp.application.ports.protocols import DocumentBlobStore, DocumentReader
from ai_idp.domain.errors import UnsupportedMediaTypeError
from ai_idp.domain.models import Document, DocumentUnit
from ai_idp.settings import Settings


class CompositeDocumentReader:
    """Dispatches document normalization to PDF, DOCX, or Image readers based on media type."""

    def __init__(self, readers: list[DocumentReader]) -> None:
        self._readers = readers

    @classmethod
    def from_settings(cls, settings: Settings) -> CompositeDocumentReader:
        return cls(
            readers=[
                PyMuPdfDocumentReader(
                    max_pages=settings.max_pdf_pages,
                    render_dpi=settings.pdf_render_dpi,
                    max_image_pixels=settings.max_image_pixels,
                ),
                MammothDocxDocumentReader(
                    max_blocks=settings.max_docx_blocks,
                    max_expanded_bytes=settings.max_expanded_bytes,
                ),
                PillowImageDocumentReader(
                    max_image_pixels=settings.max_image_pixels,
                ),
            ]
        )

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
                return reader.normalize(document, raw_bytes, blob_store)
        raise UnsupportedMediaTypeError(
            f"No document reader registered for '{document.media_type}'."
        )
