from __future__ import annotations

import io
import zipfile
from typing import Any

import mammoth
from bs4 import BeautifulSoup, Tag

from ai_idp.application.ports.protocols import DocumentBlobStore
from ai_idp.domain.enums import UnitKind
from ai_idp.domain.errors import DocumentLimitExceededError, MalformedDocumentError
from ai_idp.domain.models import Document, DocumentUnit

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_ZIP_ENTRIES = 5000


def _table_to_markdown(table_tag: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table_tag.find_all("tr"):
        cells = [" ".join(td.get_text(" ", strip=True).split()) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    padded = [r + [""] * (col_count - len(r)) for r in rows]
    lines = ["| " + " | ".join(padded[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for r in padded[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


class MammothDocxDocumentReader:
    """Normalizes DOCX files into semantic DocumentUnit blocks using Mammoth."""

    def __init__(
        self,
        *,
        max_blocks: int = 1000,
        max_expanded_bytes: int = 1024 * 1024 * 1024,
        max_block_chars: int = 4000,
    ) -> None:
        self._max_blocks = max_blocks
        self._max_expanded_bytes = max_expanded_bytes
        self._max_block_chars = max_block_chars

    def supports(self, media_type: str) -> bool:
        return media_type == DOCX_MIME

    def _validate_zip_safety(self, raw_bytes: bytes) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                infos = zf.infolist()
                if len(infos) > MAX_ZIP_ENTRIES:
                    raise DocumentLimitExceededError(
                        f"DOCX archive entry count ({len(infos)}) "
                        f"exceeds maximum ({MAX_ZIP_ENTRIES})."
                    )
                total_uncompressed = sum(info.file_size for info in infos)
                if total_uncompressed > self._max_expanded_bytes:
                    raise DocumentLimitExceededError(
                        f"DOCX expanded size ({total_uncompressed} bytes) exceeds limit "
                        f"({self._max_expanded_bytes} bytes)."
                    )
        except zipfile.BadZipFile as exc:
            raise MalformedDocumentError("Corrupted DOCX ZIP archive.") from exc

    def normalize(
        self,
        document: Document,
        raw_bytes: bytes,
        blob_store: DocumentBlobStore,
    ) -> list[DocumentUnit]:
        self._validate_zip_safety(raw_bytes)

        embedded_images: dict[str, str] = {}
        image_counter = 0

        def convert_image(image: Any) -> dict[str, str]:
            nonlocal image_counter
            image_counter += 1
            content_type = getattr(image, "content_type", "image/png") or "image/png"
            ext = "png"
            if "jpeg" in content_type or "jpg" in content_type:
                ext = "jpg"
            elif "webp" in content_type:
                ext = "webp"
            img_name = f"image{image_counter}.{ext}"
            img_key = f"artifacts/{document.document_id}/images/{img_name}"
            with image.open() as img_stream:
                img_bytes = img_stream.read()
            blob_store.put_bytes(img_key, img_bytes)
            embedded_images[img_name] = img_key
            return {"src": img_name, "alt": f"Embedded image {img_name}"}

        try:
            result = mammoth.convert_to_html(
                io.BytesIO(raw_bytes),
                convert_image=mammoth.images.img_element(convert_image),
            )
        except Exception as exc:
            raise MalformedDocumentError(f"Failed to convert DOCX with Mammoth: {exc}") from exc

        warnings = [str(m.message) for m in (result.messages or [])]
        soup = BeautifulSoup(result.value or "", "html.parser")

        raw_blocks: list[dict[str, Any]] = []
        current_heading: str | None = None
        current_lines: list[str] = []
        current_html_parts: list[str] = []
        current_images: list[str] = []
        table_count = 0

        def flush_block() -> None:
            nonlocal current_lines, current_html_parts, current_images, table_count
            text_body = "\n\n".join(line for line in current_lines if line.strip()).strip()
            if not text_body and not current_images:
                return
            raw_blocks.append(
                {
                    "heading": current_heading,
                    "text": text_body,
                    "html": "\n".join(current_html_parts),
                    "images": list(current_images),
                    "table_count": table_count,
                }
            )
            current_lines = []
            current_html_parts = []
            current_images = []
            table_count = 0

        top_nodes = list(soup.contents)
        for node in top_nodes:
            if not isinstance(node, Tag):
                txt = str(node).strip()
                if txt:
                    current_lines.append(txt)
                continue

            tag_name = (node.name or "").lower()
            if tag_name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                flush_block()
                current_heading = " ".join(node.get_text(" ", strip=True).split())
                current_lines.append(f"# {current_heading}")
                current_html_parts.append(str(node))
                for img in node.find_all("img"):
                    src = img.get("src")
                    if isinstance(src, str) and src in embedded_images:
                        current_images.append(src)
                continue

            # Check for images in this element
            node_imgs: list[str] = []
            if tag_name == "img":
                src = node.get("src")
                if isinstance(src, str) and src in embedded_images:
                    node_imgs.append(src)
            else:
                for img in node.find_all("img"):
                    src = img.get("src")
                    if isinstance(src, str) and src in embedded_images:
                        node_imgs.append(src)

            if tag_name == "table":
                md_table = _table_to_markdown(node)
                if md_table:
                    current_lines.append(md_table)
                    table_count += 1
            else:
                txt = " ".join(node.get_text(" ", strip=True).split())
                if txt:
                    current_lines.append(txt)

            for img_src in node_imgs:
                current_lines.append(f"[Embedded Image: {img_src}]")
                current_images.append(img_src)

            current_html_parts.append(str(node))

            current_char_len = sum(len(part) for part in current_lines)
            if current_char_len >= self._max_block_chars:
                flush_block()

        flush_block()

        if not raw_blocks:
            fallback_text = soup.get_text("\n", strip=True)
            raw_blocks.append(
                {
                    "heading": None,
                    "text": fallback_text,
                    "html": result.value or "",
                    "images": list(embedded_images.keys()),
                    "table_count": 0,
                }
            )

        if len(raw_blocks) > self._max_blocks:
            raise DocumentLimitExceededError(
                f"DOCX semantic block count ({len(raw_blocks)}) exceeds limit ({self._max_blocks})."
            )

        units: list[DocumentUnit] = []
        for idx, blk in enumerate(raw_blocks, start=1):
            unit_id = f"block_{idx:06d}"
            text_content = blk["text"]
            text_ref: str | None = None
            if text_content:
                text_key = f"artifacts/{document.document_id}/text/{unit_id}.txt"
                blob_store.put_text(text_key, text_content)
                text_ref = text_key

            blk_images: list[str] = blk["images"]
            primary_image_name = blk_images[0] if blk_images else None
            image_ref = embedded_images.get(primary_image_name) if primary_image_name else None

            locator: dict[str, Any] = {"block_id": unit_id, "block_index": idx}
            if blk["heading"]:
                locator["heading"] = blk["heading"]
            if primary_image_name:
                locator["embedded_image"] = primary_image_name

            units.append(
                DocumentUnit(
                    unit_id=unit_id,
                    document_id=document.document_id,
                    ordinal=idx,
                    kind=UnitKind.DOCX_BLOCK,
                    source_locator=locator,
                    native_text_ref=text_ref,
                    image_ref=image_ref,
                    metadata={
                        "heading": blk["heading"],
                        "table_count": blk["table_count"],
                        "embedded_images": blk_images,
                        "text_character_count": len(text_content),
                        "conversion_warnings": warnings[:10],
                    },
                )
            )
        return units
