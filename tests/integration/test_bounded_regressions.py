import io
import re

import pymupdf
from fastapi.testclient import TestClient
from openpyxl import Workbook

from ai_idp.adapters.inbound.http.app import create_app
from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.application.ports.protocols import ExtractionBatchResult
from ai_idp.domain.enums import Modality
from ai_idp.domain.models import Evidence
from ai_idp.settings import Settings
from scripts.generate_spreadsheet_fixture import workbook_bytes
from tests.integration.test_spreadsheet_pages import SCHEMA, AllRelevant, RegisterExtractor, setup


async def test_large_nested_collection_completes_and_exports_exact_records(tmp_path):
    class NestedRegister(RegisterExtractor):
        async def extract_fields(self, **kwargs):
            result = await super().extract_fields(**kwargs)
            target = kwargs["target_fields"][0]
            assert re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", target.name)
            result.data = {target.name: result.data["items"]}
            result.evidence_by_field = {
                target.path + path[len("/items") :]: citations
                for path, citations in result.evidence_by_field.items()
            }
            return result

    core, client = setup(tmp_path, NestedRegister(), max_model_calls=1000)
    document = client.post(
        "/v1/documents", files={"file": ("nested.xlsx", workbook_bytes(300, 1))}
    ).json()
    schema = {"type": "object", "properties": {"payload": SCHEMA}, "required": ["payload"]}
    job = client.post(
        "/v1/extractions", json={"document_id": document["document_id"], "schema": schema}
    ).json()
    result = await core.pipeline_service.execute_job(job["job_id"])
    assert len(result.data["payload"]["items"]) == 300
    assert result.data["payload"]["items"][-1]["id"] == "LOT-000299"
    assert result.schema_valid
    assert not result.unresolved_fields
    assert client.get(f"/v1/extractions/{job['job_id']}/result/export").json() == result.data


async def test_continuation_preserves_two_records_on_the_same_worksheet_row(tmp_path):
    class WideExtractor:
        async def extract_fields(self, **kwargs):
            payload = kwargs["unit_inputs"][0][0]
            records = [
                ("A1: LEFT", {"id": "LEFT", "amount": 1}),
                ("C1: RIGHT", {"id": "RIGHT", "amount": 2}),
            ]
            available = [
                (anchor, item) for anchor, item in records if anchor in payload.native_text
            ]
            chosen = available[: kwargs["spec"].output_page["limit"]]
            return ExtractionBatchResult(
                data={"items": [item for _, item in chosen]},
                evidence_by_field={
                    f"/items/{i}/id": [Evidence(unit_id=payload.unit.unit_id, quote=item["id"])]
                    for i, (_, item) in enumerate(chosen)
                },
                record_anchors=[{"quote": anchor, "occurrence": 0} for anchor, _ in chosen],
                has_more=len(chosen) < len(available),
                cursor=chosen[-1][0] if chosen else "",
                model_id=kwargs["model_id"],
            )

    core, client = setup(tmp_path, WideExtractor(), extraction_page_items=1)
    workbook = Workbook()
    workbook.active.append(["LEFT", 1, "RIGHT", 2])
    data = io.BytesIO()
    workbook.save(data)
    document = client.post("/v1/documents", files={"file": ("wide.xlsx", data.getvalue())}).json()
    job = client.post(
        "/v1/extractions", json={"document_id": document["document_id"], "schema": SCHEMA}
    ).json()
    result = await core.pipeline_service.execute_job(job["job_id"])
    assert result.data["items"] == [{"id": "LEFT", "amount": 1}, {"id": "RIGHT", "amount": 2}]


def test_large_pdf_prepares_without_rendering_and_payloads_load_images_only_when_needed(tmp_path):
    core = build_container(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{tmp_path.as_posix()}/core.db",
            local_storage_root=tmp_path / "files",
            local_telemetry_root=tmp_path / "traces",
        ),
        decision_engine=AllRelevant(),
        extraction_engine=RegisterExtractor(),
        create_tables=True,
    )
    pdf = pymupdf.open()
    for i in range(40):
        pdf.new_page().insert_text((40, 60), f"SYNTHETIC PAGE {i + 1}")
    document = core.ingest_use_case.execute(raw_bytes=pdf.tobytes(), filename="large.pdf")
    pdf.close()
    units = core.job_repo.get_units(document.document_id)
    assert len(units) == 40
    assert not list((tmp_path / "files").rglob("*.png"))
    payloads = core.pipeline_service._load_unit_payloads(units, max_prepared_bytes=1024 * 1024)
    assert all(
        p.image_bytes is None and not p.additional_images and p.image_count == 1 for p in payloads
    )
    assert not list((tmp_path / "files").rglob("*.png"))
    from ai_idp.application.services.batching import unit_batches

    unit_batches([(p, Modality.TEXT) for p in payloads], max_units=8, max_bytes=1024 * 1024)
    assert not list((tmp_path / "files").rglob("*.png"))
    assert list(payloads[17].images())[0][0].startswith(b"\x89PNG")
    assert len(list((tmp_path / "files").rglob("*.png"))) == 1
    from concurrent.futures import ThreadPoolExecutor

    from ai_idp.adapters.outbound.documents.pdf_artifacts import PdfArtifactStore

    other_store = PdfArtifactStore(core.settings)
    with ThreadPoolExecutor(max_workers=2) as executor:
        reads = list(
            executor.map(
                lambda store: store.get_bytes(units[21].image_ref), [core.blob_store, other_store]
            )
        )
    assert reads[0] == reads[1]
    assert len(list((tmp_path / "files").rglob("*.png"))) == 2
    client = TestClient(create_app(core))
    estimate = client.post(
        f"/v1/documents/{document.document_id}/estimate",
        json={"document_id": document.document_id, "schema": SCHEMA},
    )
    assert estimate.status_code == 200
    assert estimate.json()["source_units"] == 40
    assert estimate.json()["warnings"]
    assert not core.job_repo.get_units(document.document_id)[0].metadata.get("image_sha256")


def test_minimum_routing_budget_is_checked_before_creating_paid_work(tmp_path):
    import pytest

    from ai_idp.domain.errors import DomainError

    core, client = setup(tmp_path, RegisterExtractor(), relevance_batch_units=1, max_model_calls=1)
    document = client.post(
        "/v1/documents", files={"file": ("many.xlsx", workbook_bytes(80, 1))}
    ).json()
    with pytest.raises(DomainError, match="minimum routing"):
        core.request_extraction_use_case.execute(
            document_id=document["document_id"], schema_json=SCHEMA
        )
    estimate = client.post(
        f"/v1/documents/{document['document_id']}/estimate",
        json={"document_id": document["document_id"], "schema": SCHEMA},
    ).json()
    assert not estimate["can_fit_minimum"]
    assert estimate["minimum_routing_calls"] == 4
