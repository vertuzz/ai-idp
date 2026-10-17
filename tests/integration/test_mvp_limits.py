import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from ai_idp.adapters.inbound.http.app import create_app
from ai_idp.adapters.outbound.persistence.model_limiter import DatabaseModelLimiter
from ai_idp.application.ports.protocols import ExtractionBatchResult
from ai_idp.domain.errors import BudgetExhaustedError, JobTimeLimitExceededError
from ai_idp.domain.models import Evidence, UsageRecord
from tests.integration.test_pipeline_recovery import SCHEMA, ControlledExtractor, setup


async def test_call_budget_stops_new_work_and_time_limit_is_terminal(tmp_path):
    c, _, job = setup(tmp_path, max_model_calls=1)
    with pytest.raises(BudgetExhaustedError):
        await c.pipeline_service.execute_job(job.job_id)
    assert c.job_repo.get_job(job.job_id).status.value == "failed"

    class SlowExtractor(ControlledExtractor):
        async def extract_fields(self, **kwargs):
            await asyncio.sleep(1)
            return await super().extract_fields(**kwargs)

    (tmp_path / "slow").mkdir()
    c, _, job = setup(tmp_path / "slow", extractor=SlowExtractor(), max_job_seconds=0.05)
    with pytest.raises(JobTimeLimitExceededError):
        await c.pipeline_service.execute_job(job.job_id)
    assert c.job_repo.get_job(job.job_id).status.value == "failed"


def test_shared_limiter_enforces_capacity_across_instances_and_releases(tmp_path):
    c, _, _ = setup(tmp_path)

    def limiter():
        return DatabaseModelLimiter(
            c.job_repo._session_factory,
            global_limit=2,
            per_model={"*": 1},
            requests_per_minute={"*": 1_000_000},
        )

    first, second = limiter(), limiter()
    assert first.try_acquire("a", "first")
    assert not second.try_acquire("a", "same-model")
    assert second.try_acquire("b", "second")
    assert not first.try_acquire("c", "over-global")
    first.release("first")
    assert second.try_acquire("a", "replacement")


async def test_http_idempotency_conflict_and_decision_pagination(tmp_path):
    c, doc, job = setup(tmp_path)
    await c.pipeline_service.execute_job(job.job_id)
    client = TestClient(create_app(c))
    payload = {"document_id": doc.document_id, "schema": SCHEMA}
    headers = {"Idempotency-Key": "repeat"}
    assert client.post("/v1/extractions", json=payload, headers=headers).status_code == 202
    changed = {**payload, "instructions": "A different request"}
    assert client.post("/v1/extractions", json=changed, headers=headers).status_code == 409
    assert (
        client.post("/v1/extractions", json={**payload, "model_profile": "typo"}).status_code == 422
    )
    page = client.get(f"/v1/extractions/{job.job_id}/decisions?limit=1").json()
    assert len(page["decisions"]) == 1
    assert page["next_offset"] == 1
    next_page = client.get(f"/v1/extractions/{job.job_id}/decisions?limit=1&offset=1").json()
    assert page["decisions"][0]["decision_id"] != next_page["decisions"][0]["decision_id"]
    units = client.get(f"/v1/documents/{doc.document_id}/units").json()["units"]
    uid = units[0]["unit_id"]
    text_response = client.get(f"/v1/documents/{doc.document_id}/units/{uid}/text")
    assert text_response.status_code == 200
    assert "TEST-NATIVE-01" in text_response.text
    image = client.get(f"/v1/documents/{doc.document_id}/units/{uid}/images/0")
    assert image.content.startswith(b"\x89PNG")
    assert image.headers["cache-control"] == "no-store"
    assert client.get(f"/v1/documents/{doc.document_id}/content").content.startswith(b"%PDF-")


def test_oversized_chunked_upload_is_rejected_before_document_work(tmp_path):
    c, _, _ = setup(tmp_path, max_upload_mib=1)
    client = TestClient(create_app(c))
    response = client.post(
        "/v1/documents", files={"file": ("oversize.pdf", b"%PDF-" + b"x" * 1_200_000)}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"


class MergeExtractor:
    def __init__(self):
        self.calls = []

    async def extract_fields(self, **kw):
        inputs = kw["unit_inputs"]
        self.calls.append([p.unit.unit_id for p, _ in inputs])
        if inputs[0][0].unit.unit_id.startswith("candidate"):
            candidate = json.loads(inputs[-1][0].native_text)
            data = candidate["data"]
            evidence = {
                p: [Evidence.model_validate(e) for e in evs]
                for p, evs in candidate["evidence"].items()
            }
        else:
            data = {"record_id": inputs[-1][0].unit.unit_id}
            evidence = {"/record_id": [Evidence(unit_id=inputs[-1][0].unit.unit_id)]}
        return ExtractionBatchResult(
            data=data,
            evidence_by_field=evidence,
            model_id=kw["model_id"],
            usage=UsageRecord(
                usage_id=uuid.uuid4().hex,
                job_id=kw["job_id"],
                stage=kw["stage_name"],
                model_id=kw["model_id"],
            ),
        )


async def test_large_input_batches_use_model_merge_and_original_evidence(tmp_path):
    from pathlib import Path

    extractor = MergeExtractor()
    c, _, _ = setup(tmp_path, extractor=extractor, max_units_per_call=2)
    path = Path(__file__).resolve().parents[2] / "eval/fixtures/synthetic/synthetic-mixed-01.pdf"
    doc = c.ingest_use_case.execute(raw_bytes=path.read_bytes(), filename=path.name)
    assert len(c.job_repo.get_units(doc.document_id)) > 2
    job = c.request_extraction_use_case.execute(
        document_id=doc.document_id, schema_json=SCHEMA, model_profile="always_vision"
    )
    result = await c.pipeline_service.execute_job(job.job_id)
    assert len(extractor.calls) >= 3
    assert all(len(call) <= 2 for call in extractor.calls)
    assert any(call[0].startswith("candidate") for call in extractor.calls)
    assert result.fields["/record_id"].sources[0].unit_id.startswith("page_")
