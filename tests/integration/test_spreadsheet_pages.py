"""Real upload/isolated decoding/worker/persistence/HTTP paging with controlled models."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from ai_idp.adapters.inbound.http.app import create_app
from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.application.ports.protocols import ExtractionBatchResult
from ai_idp.domain.enums import VerificationStatus
from ai_idp.domain.errors import ModelOutputLimitExceededError
from ai_idp.domain.models import Evidence, UsageRecord
from ai_idp.settings import Settings
from scripts.generate_spreadsheet_fixture import workbook_bytes
from tests.integration.test_api_and_worker import FakeDecisionEngine

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "All register records",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "amount": {"type": "number"}},
                "required": ["id", "amount"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
}


class AllRelevant(FakeDecisionEngine):
    async def score_relevance(self, *args, **kwargs):
        result = await super().score_relevance(*args, **kwargs)
        result.score = 0.99
        return result


class RegisterExtractor:
    def __init__(self, *, stall=False, overflow=False):
        self.calls = 0
        self.stall, self.overflow = stall, overflow

    async def extract_fields(self, **kw):
        self.calls += 1
        assert len(kw["unit_inputs"]) == 1, "Collection fragments must never reach a model merge."
        payload = kw["unit_inputs"][0][0]
        request = kw["spec"].output_page
        if self.overflow and request["limit"] > 3:
            raise ModelOutputLimitExceededError("Simulated length finish.")
        after = int(request["after"] or "0")
        rows = {}
        for col, row, text in re.findall(r"^([A-Z]+)(\d+): ([^\n]+)", payload.native_text, re.M):
            rows.setdefault(int(row), {})[col] = text
        eligible = [
            (r, v) for r, v in rows.items() if r > after and v.get("A", "").startswith("LOT-")
        ]
        chosen = eligible[: request["limit"]]
        evidence = {}
        items = []
        for index, (row, values) in enumerate(chosen):
            item = {"id": values["A"], "amount": float(values["D"])}
            items.append(item)
            for path, quote in [
                (f"/items/{index}/id", values["A"]),
                (f"/items/{index}/amount", values["D"]),
                (f"/items/{index}", f"A{row}: {values['A']}"),
            ]:
                evidence[path] = [Evidence(unit_id=payload.unit.unit_id, quote=quote)]
        more = len(eligible) > len(chosen)
        return ExtractionBatchResult(
            data={"items": items},
            evidence_by_field=evidence,
            has_more=more or self.stall,
            record_anchors=[
                {"quote": f"A{row}: {values['A']}", "occurrence": 0} for row, values in chosen
            ],
            cursor="same" if self.stall else str(chosen[-1][0]) if chosen else "",
            model_id=kw["model_id"],
            usage=UsageRecord(
                usage_id=uuid.uuid4().hex,
                job_id=kw["job_id"],
                stage=kw["stage_name"],
                model_id=kw["model_id"],
            ),
        )


def setup(tmp_path, extractor, **options):
    core = build_container(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{(tmp_path / 'core.db').as_posix()}",
            local_storage_root=tmp_path / "files",
            local_telemetry_root=tmp_path / "telemetry",
            extraction_page_items=options.pop("extraction_page_items", 7),
            max_field_extra_attempts=0,
            **options,
        ),
        decision_engine=AllRelevant(),
        extraction_engine=extractor,
        create_tables=True,
    )
    return core, TestClient(create_app(core))


async def test_large_workbook_exact_pages_export_and_global_evidence(tmp_path):
    extractor = RegisterExtractor()
    core, client = setup(tmp_path, extractor)
    upload = client.post("/v1/documents", files={"file": ("register.xlsx", workbook_bytes(205, 2))})
    assert upload.status_code == 201, upload.text
    doc = upload.json()["document_id"]
    job_id = client.post("/v1/extractions", json={"document_id": doc, "schema": SCHEMA}).json()[
        "job_id"
    ]
    await core.pipeline_service.execute_job(job_id)
    manifest = client.get(f"/v1/extractions/{job_id}/result/manifest").json()
    assert manifest["complete"] and manifest["schema_valid"]
    assert manifest["collections"][0]["total_items"] == 205
    seen, cursor = [], None
    for _ in range(5):
        params = {"path": "/items", **({"cursor": cursor} if cursor else {})}
        response = client.get(f"/v1/extractions/{job_id}/result/collections", params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(response.content) < 1024 * 1024
        assert f"/items/{page['start_index']}/id" in page["fields"]
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 205
    assert client.get(f"/v1/extractions/{job_id}/result").status_code == 413
    assert [r["id"] for r in seen] == [f"LOT-{i:06d}" for i in range(205)]
    assert client.get(f"/v1/extractions/{job_id}/result/export").json() == {"items": seen}
    assert (
        client.get(
            f"/v1/extractions/{job_id}/result/collections",
            params={"path": "/items", "cursor": "invalid"},
        ).status_code
        == 409
    )
    calls = extractor.calls
    await core.pipeline_service.execute_job(job_id)
    assert extractor.calls == calls


async def test_truncation_halves_page_size_without_repeating_saved_rows(tmp_path):
    core, client = setup(tmp_path, RegisterExtractor(overflow=True))
    doc = client.post(
        "/v1/documents", files={"file": ("register.xlsx", workbook_bytes(18, 1))}
    ).json()["document_id"]
    job_id = client.post("/v1/extractions", json={"document_id": doc, "schema": SCHEMA}).json()[
        "job_id"
    ]
    result = await core.pipeline_service.execute_job(job_id)
    assert len(result.data["items"]) == 18
    assert len({r["id"] for r in result.data["items"]}) == 18


async def test_stalled_output_fails_and_exposes_incomplete_saved_parts(tmp_path):
    core, client = setup(tmp_path, RegisterExtractor(stall=True))
    doc = client.post(
        "/v1/documents", files={"file": ("register.xlsx", workbook_bytes(18, 1))}
    ).json()["document_id"]
    job_id = client.post("/v1/extractions", json={"document_id": doc, "schema": SCHEMA}).json()[
        "job_id"
    ]
    with pytest.raises((ModelOutputLimitExceededError, ValueError)):
        await core.pipeline_service.execute_job(job_id)
    response = client.get(f"/v1/extractions/{job_id}/result/parts").json()
    assert response["parts"] and not response["complete"]
    assert client.get(f"/v1/extractions/{job_id}/result/manifest").status_code == 409


async def test_independent_source_count_recovers_an_omitted_record(tmp_path):
    class CountDecision(AllRelevant):
        async def verify_fields(self, **kw):
            result = await super().verify_fields(**kw)
            for target, value, _ in kw["fields_to_verify"]:
                if target.name == "owned_record_count":
                    actual = sum(
                        len(re.findall(r"^A\d+: LOT-", p.native_text or "", re.M))
                        for p in kw["unit_payloads_by_id"].values()
                    )
                    if value != actual:
                        result.outcomes[target.path].status = VerificationStatus.CONTRADICTED
                        result.outcomes[target.path].raw_probabilities = {"CONTRADICTED": 0.99}
            return result

    class OmittingExtractor(RegisterExtractor):
        async def extract_fields(self, **kw):
            result = await super().extract_fields(**kw)
            if kw["stage_name"] == "extracting" and not kw["spec"].output_page["after"]:
                if result.data["items"] and not kw["spec"].output_page["source_text_start"]:
                    result.data["items"].pop()
                    result.record_anchors.pop()
                    result.has_more = False
            return result

    core, client = setup(tmp_path, OmittingExtractor())
    core.pipeline_service._decision_engine = CountDecision()
    doc = client.post(
        "/v1/documents", files={"file": ("register.xlsx", workbook_bytes(18, 1))}
    ).json()["document_id"]
    job_id = client.post("/v1/extractions", json={"document_id": doc, "schema": SCHEMA}).json()[
        "job_id"
    ]
    result = await core.pipeline_service.execute_job(job_id)
    assert [r["id"] for r in result.data["items"]] == [f"LOT-{i:06d}" for i in range(18)]


async def test_global_evidence_indices_are_resolved_by_owned_record_anchors(tmp_path):
    class GlobalIndices(RegisterExtractor):
        async def extract_fields(self, **kw):
            result = await super().extract_fields(**kw)
            changed = {}
            for pointer, sources in result.evidence_by_field.items():
                parts = pointer.split("/")
                if len(parts) > 2 and parts[2].isdigit():
                    record = result.data["items"][int(parts[2])]
                    parts[2] = str(int(record["id"].split("-")[-1]))
                changed["/".join(parts)] = sources
            result.evidence_by_field = changed
            return result

    core, client = setup(tmp_path, GlobalIndices())
    doc = client.post(
        "/v1/documents", files={"file": ("register.xlsx", workbook_bytes(40, 1))}
    ).json()["document_id"]
    job_id = client.post("/v1/extractions", json={"document_id": doc, "schema": SCHEMA}).json()[
        "job_id"
    ]
    result = await core.pipeline_service.execute_job(job_id)
    assert result.fields["/items/31/id"].sources[0].quote == "LOT-000031"
    assert result.fields["/items/31/amount"].sources[0].quote == "40"
    assert result.unresolved_fields == []
