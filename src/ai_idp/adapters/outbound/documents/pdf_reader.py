from __future__ import annotations

import math

import pymupdf

from ai_idp.application.ports.protocols import DocumentBlobStore
from ai_idp.domain.enums import UnitKind
from ai_idp.domain.errors import DocumentLimitExceededError, MalformedDocumentError
from ai_idp.domain.models import Document, DocumentUnit


class PyMuPdfDocumentReader:
    """Normalizes PDF documents into page-level DocumentUnit objects."""

    def __init__(
        self,
        *,
        max_pages: int = 1000,
        render_dpi: int = 150,
        max_image_pixels: int = 40_000_000,
    ) -> None:
        self._max_pages = max_pages
        self._render_dpi = render_dpi
        self._max_image_pixels = max_image_pixels

    def supports(self, media_type: str) -> bool:
        return media_type == "application/pdf"

    def normalize(
        self,
        document: Document,
        raw_bytes: bytes,
        blob_store: DocumentBlobStore,
    ) -> list[DocumentUnit]:
        try:
            pdf = pymupdf.open(stream=raw_bytes, filetype="pdf")
        except Exception as exc:
            raise MalformedDocumentError(f"Failed to open PDF document: {exc}") from exc

        try:
            page_count = len(pdf)
            if page_count == 0:
                raise MalformedDocumentError("PDF document contains zero pages.")
            if page_count > self._max_pages:
                raise DocumentLimitExceededError(
                    f"PDF page count ({page_count}) exceeds limit ({self._max_pages})."
                )

            units: list[DocumentUnit] = []
            for idx in range(page_count):
                page_number = idx + 1
                unit_id = f"page_{page_number:06d}"
                page = pdf[idx]
                rect = page.rect
                width_pt = round(float(rect.width), 2)
                height_pt = round(float(rect.height), 2)

                native_text = page.get_text("text") or ""
                clean_text = native_text.strip()
                text_ref: str | None = None
                if clean_text:
                    text_key = f"artifacts/{document.document_id}/text/{unit_id}.txt"
                    blob_store.put_text(text_key, clean_text)
                    text_ref = text_key

                # Calculate safe DPI so rendered image stays within max_image_pixels
                scale = self._render_dpi / 72.0
                est_pixels = (width_pt * scale) * (height_pt * scale)
                if est_pixels > self._max_image_pixels and est_pixels > 0:
                    scale = math.sqrt(self._max_image_pixels / max(1.0, width_pt * height_pt))
                matrix = pymupdf.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                png_bytes = pix.tobytes("png")
                image_key = f"artifacts/{document.document_id}/render/{unit_id}.png"
                blob_store.put_bytes(image_key, png_bytes)

                image_list = page.get_images(full=False)
                units.append(
                    DocumentUnit(
                        unit_id=unit_id,
                        document_id=document.document_id,
                        ordinal=page_number,
                        kind=UnitKind.PDF_PAGE,
                        source_locator={"page_number": page_number},
                        native_text_ref=text_ref,
                        image_ref=image_key,
                        metadata={
                            "width_points": width_pt,
                            "height_points": height_pt,
                            "rendered_width_px": pix.width,
                            "rendered_height_px": pix.height,
                            "image_count": len(image_list),
                            "text_character_count": len(clean_text),
                        },
                    )
                )
            return units
        finally:
            pdf.close()
