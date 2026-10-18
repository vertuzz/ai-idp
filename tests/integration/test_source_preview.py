from __future__ import annotations

import hashlib

import pymupdf
import pytest
from fastapi.testclient import TestClient

from ai_idp.adapters.inbound.http.app import create_app
from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.adapters.outbound.documents.docx_reader import _safe_preview_html
from ai_idp.settings import Settings


@pytest.fixture
def client(tmp_path):
    container = build_container(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'core.sqlite3').as_posix()}",
            local_storage_root=tmp_path / "files",
            local_telemetry_root=tmp_path / "telemetry",
            openrouter_api_key="",
            api_key="",
        ),
        create_tables=True,
    )
    return TestClient(create_app(container))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_native_pdf_location_uses_display_coordinates_and_immutable_text(client, rotation):
    pdf = pymupdf.open()
    page = pdf.new_page(width=500, height=650)
    page.insert_text((100, 180), "Invoice INV-0042", fontsize=14)
    page.insert_text((100, 230), "Total EUR 1452.00", fontsize=14)
    page.set_cropbox(pymupdf.Rect(20, 30, 480, 620))
    page.set_rotation(rotation)
    uploaded = client.post(
        "/v1/documents", files={"file": ("source.pdf", pdf.tobytes(), "application/pdf")}
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["document_id"]
    base = f"/v1/documents/{document_id}/units/page_000001"
    preview = client.get(f"{base}/preview")
    text = preview.json()["text"]
    assert preview.headers["Cache-Control"] == "no-store"
    location = client.post(f"{base}/location", json={"quote": "EUR 1452.00"}).json()
    assert location["status"] == "exact"
    assert len(location["regions"]) == 2
    assert location["artifact_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    image = client.get(f"{base}/images/0").content
    assert location["image_sha256"] == hashlib.sha256(image).hexdigest()
    expected = page.search_for("1452.00")[0] * page.rotation_matrix
    actual = location["regions"][1]
    assert actual == pytest.approx(
        [
            expected.x0 / page.rect.width,
            expected.y0 / page.rect.height,
            expected.x1 / page.rect.width,
            expected.y1 / page.rect.height,
        ]
    )
    for box in location["regions"]:
        assert 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
    stale = client.post(
        f"{base}/location", json={"quote": "1452.00", "artifact_sha256": "bad"}
    ).json()
    assert stale["status"] == "unavailable"
    assert stale["regions"] == []


def test_repeated_quotes_partial_values_and_invalid_spans_do_not_invent_boxes(client):
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 70), "Total 1000.00\nTotal 1000.00")
    response = client.post(
        "/v1/documents", files={"file": ("repeated.pdf", pdf.tobytes(), "application/pdf")}
    )
    document_id = response.json()["document_id"]
    base = f"/v1/documents/{document_id}/units/page_000001"
    assert (
        client.post(f"{base}/location", json={"quote": "1000.00"}).json()["status"] == "ambiguous"
    )
    assert client.post(f"{base}/location", json={"quote": "999"}).json()["status"] == "unit_only"
    assert (
        client.post(f"{base}/location", json={"start": 0, "end": 9999}).json()["status"]
        == "unavailable"
    )
    text = client.get(f"{base}/preview").json()["text"]
    start = text.index("1000.00")
    result = client.post(
        f"{base}/location", json={"start": start, "end": start + 3, "quote": "100"}
    ).json()
    assert result["status"] == "unit_only" and result["reason"] == "partial_token"
    exact = client.post(
        f"{base}/location", json={"start": start, "end": start + 7, "quote": "1000.00"}
    ).json()
    assert exact["status"] == "exact"


def test_docx_preview_removes_active_content_and_external_resources():
    sanitized = _safe_preview_html(
        '<p onclick="bad()">Hello <b>world</b></p>'
        '<script><a href="bad">danger</a></script><img src="https://evil.example/a">'
        '<table style="background:url(https://evil.example)"><tr><td>100</td></tr></table>'
    )
    assert "Hello <b>world</b>" in sanitized
    assert "<table>" in sanitized
    for dangerous in ("onclick", "script", "src=", "href=", "style=", "evil.example", "danger"):
        assert dangerous not in sanitized
