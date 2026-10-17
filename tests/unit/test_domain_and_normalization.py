from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from ai_idp.adapters.outbound.documents.composite_reader import CompositeDocumentReader
from ai_idp.adapters.outbound.storage.local import LocalDocumentBlobStore
from ai_idp.domain.enums import DocumentStatus, Modality, UnitKind
from ai_idp.domain.errors import DomainError, InvalidSchemaError
from ai_idp.domain.models import Document
from ai_idp.domain.schema_normalizer import (
    normalize_extraction_schema,
    validate_data_against_schema,
)
from ai_idp.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_schema_normalizer_accepts_nested_arrays_and_rejects_ref():
    schema = {
        "type": "object",
        "properties": {
            "invoice_id": {"type": "string", "description": "Invoice identifier"},
            "notes": {"type": ["string", "null"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["name", "amount"],
                },
            },
        },
        "required": ["invoice_id", "items"],
    }
    spec = normalize_extraction_schema(schema, instructions="Extract carefully.")
    assert len(spec.fields) == 3
    by_name = {f.name: f for f in spec.fields}
    assert by_name["invoice_id"].required is True
    assert by_name["invoice_id"].nullable is False
    assert by_name["notes"].nullable is True
    assert by_name["items"].is_array is True

    valid, errs = validate_data_against_schema(
        {"invoice_id": "INV-1", "notes": None, "items": [{"name": "A", "amount": 10.5}]},
        schema,
    )
    assert valid is True
    assert errs == []

    with pytest.raises(InvalidSchemaError):
        normalize_extraction_schema(
            {
                "type": "object",
                "properties": {"bad": {"$ref": "#/$defs/item"}},
            }
        )


def test_local_blob_store_prevents_path_traversal(tmp_path: Path):
    store = LocalDocumentBlobStore(tmp_path / "blobs")
    store.put_text("docs/hello.txt", "world")
    assert store.exists("docs/hello.txt")
    assert store.get_text("docs/hello.txt") == "world"

    with pytest.raises(DomainError):
        store.put_text("../escape.txt", "bad")


def test_composite_reader_normalizes_pdf_docx_and_tiff(tmp_path: Path):
    settings = Settings(local_storage_root=tmp_path)
    store = LocalDocumentBlobStore(tmp_path)
    reader = CompositeDocumentReader.from_settings(settings)

    # 1. Multi-page PDF fixture from synthetic corpus
    pdf_path = ROOT / "eval" / "fixtures" / "synthetic" / "synthetic-mixed-01.pdf"
    pdf_bytes = pdf_path.read_bytes()
    pdf_doc = Document(
        document_id="doc_pdf_01",
        filename="synthetic-mixed-01.pdf",
        media_type="application/pdf",
        sha256="abc",
        bytes_size=len(pdf_bytes),
        storage_key="originals/doc_pdf_01.bin",
        status=DocumentStatus.STORED,
    )
    pdf_units = reader.normalize(pdf_doc, pdf_bytes, store)
    assert len(pdf_units) >= 3
    assert pdf_units[0].unit_id == "page_000001"
    assert pdf_units[0].kind == UnitKind.PDF_PAGE
    assert pdf_units[0].source_locator == {"page_number": 1}
    assert pdf_units[0].image_ref is not None
    assert store.exists(pdf_units[0].image_ref)

    # 2. DOCX fixture with tables and embedded image
    docx_path = ROOT / "eval" / "fixtures" / "synthetic" / "synthetic-docx-01.docx"
    docx_bytes = docx_path.read_bytes()
    docx_doc = Document(
        document_id="doc_docx_01",
        filename="synthetic-docx-01.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sha256="def",
        bytes_size=len(docx_bytes),
        storage_key="originals/doc_docx_01.bin",
        status=DocumentStatus.STORED,
    )
    docx_units = reader.normalize(docx_doc, docx_bytes, store)
    assert len(docx_units) >= 1
    assert all(u.kind == UnitKind.DOCX_BLOCK for u in docx_units)
    assert any(u.image_ref is not None for u in docx_units)
    assert any(Modality.TEXT_AND_VISION in u.available_modalities for u in docx_units)

    # 3. Multi-frame TIFF image
    frames = [
        Image.new("RGB", (120, 80), color=(255, 255, 255)),
        Image.new("RGB", (120, 80), color=(200, 200, 200)),
    ]
    tiff_buf = io.BytesIO()
    frames[0].save(tiff_buf, format="TIFF", save_all=True, append_images=frames[1:])
    tiff_bytes = tiff_buf.getvalue()
    tiff_doc = Document(
        document_id="doc_tiff_01",
        filename="multi.tiff",
        media_type="image/tiff",
        sha256="ghi",
        bytes_size=len(tiff_bytes),
        storage_key="originals/doc_tiff_01.bin",
        status=DocumentStatus.STORED,
    )
    tiff_units = reader.normalize(tiff_doc, tiff_bytes, store)
    assert len(tiff_units) == 2
    assert tiff_units[0].unit_id == "frame_000001"
    assert tiff_units[1].unit_id == "frame_000002"
    assert tiff_units[1].source_locator == {"frame_index": 1}
