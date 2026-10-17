from __future__ import annotations

import io

from PIL import Image, ImageSequence

from ai_idp.application.ports.protocols import DocumentBlobStore
from ai_idp.domain.enums import UnitKind
from ai_idp.domain.errors import DocumentLimitExceededError, MalformedDocumentError
from ai_idp.domain.models import Document, DocumentUnit

SUPPORTED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/tiff"})


class PillowImageDocumentReader:
    """Normalizes PNG, JPEG, and multi-frame TIFF files into frame-level DocumentUnit objects."""

    def __init__(
        self,
        *,
        max_frames: int = 200,
        max_image_pixels: int = 40_000_000,
    ) -> None:
        self._max_frames = max_frames
        self._max_image_pixels = max_image_pixels

    def supports(self, media_type: str) -> bool:
        return media_type in SUPPORTED_IMAGE_MIMES

    def normalize(
        self,
        document: Document,
        raw_bytes: bytes,
        blob_store: DocumentBlobStore,
    ) -> list[DocumentUnit]:
        Image.MAX_IMAGE_PIXELS = self._max_image_pixels
        try:
            img = Image.open(io.BytesIO(raw_bytes))
        except Image.DecompressionBombError as exc:
            raise DocumentLimitExceededError(
                f"Image pixel count exceeds maximum allowed ({self._max_image_pixels})."
            ) from exc
        except Exception as exc:
            raise MalformedDocumentError(f"Failed to decode image file: {exc}") from exc

        units: list[DocumentUnit] = []
        try:
            for frame_idx, frame in enumerate(ImageSequence.Iterator(img)):
                if frame_idx >= self._max_frames:
                    raise DocumentLimitExceededError(
                        f"Image frame count exceeds maximum allowed ({self._max_frames})."
                    )
                width, height = frame.size
                if width * height > self._max_image_pixels:
                    raise DocumentLimitExceededError(
                        f"Frame {frame_idx} pixels ({width * height}) "
                        f"exceed limit ({self._max_image_pixels})."
                    )
                ordinal = frame_idx + 1
                unit_id = f"frame_{ordinal:06d}"

                rgb_frame = (
                    frame.convert("RGB") if frame.mode not in ("RGB", "RGBA", "L") else frame.copy()
                )
                buf = io.BytesIO()
                rgb_frame.save(buf, format="PNG")
                image_key = f"artifacts/{document.document_id}/render/{unit_id}.png"
                blob_store.put_bytes(image_key, buf.getvalue())

                units.append(
                    DocumentUnit(
                        unit_id=unit_id,
                        document_id=document.document_id,
                        ordinal=ordinal,
                        kind=UnitKind.IMAGE_FRAME,
                        source_locator={"frame_index": frame_idx},
                        native_text_ref=None,
                        image_ref=image_key,
                        metadata={
                            "width_px": width,
                            "height_px": height,
                            "frame_index": frame_idx,
                            "format": img.format or document.media_type,
                        },
                    )
                )
        finally:
            img.close()

        if not units:
            raise MalformedDocumentError("Image contains zero readable frames.")
        return units
