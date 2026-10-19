from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from ai_idp.adapters.inbound.http.app import create_app
from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.adapters.outbound.persistence.suggestions import SuggestionRow
from ai_idp.application.services.request_budget import active_request_budget
from ai_idp.domain.enums import UnitKind
from ai_idp.domain.errors import InvalidSchemaError
from ai_idp.domain.models import Document, DocumentUnit, UsageRecord
from ai_idp.domain.schema_suggestion import SchemaProposal, compile_proposal
from ai_idp.settings import Settings
from ai_idp.workers.runner import WorkerRunner


class DiscoveryModels:
    def __init__(self):
        self.compatibility = "SHARED"
        self.support = "SUPPORTED"
        self.calls = []
        self.invalid = 0
        self.cost = 0.001
        self.pause = None

    def usage(self, job_id, model_id):
        budget = active_request_budget.get()
        budget.reserve()
        budget.report_cost(self.cost)
        return UsageRecord(
            usage_id=f"u{len(self.calls)}",
            job_id=job_id,
            stage="test",
            model_id=model_id,
            estimated_cost_usd=self.cost,
            tokens_in=10,
        )

    async def assess_schema(self, job_id, payloads, questions, model_id):
        self.calls.append(next(iter(questions)))
        usage = self.usage(job_id, model_id)
        result = {}
        for key in questions:
            choice = (
                self.compatibility
                if key == "compatibility"
                else self.support
                if key.startswith("field_")
                else "TEXT"
            )
            result[key] = {"choice": choice, "distribution": {}}
        return result, usage

    async def propose_schema(self, job_id, payloads, model_id, repair=""):
        self.calls.append("generate")
        usage = self.usage(job_id, model_id)
        if self.pause:
            self.pause.set()
            await asyncio.Event().wait()
        sources = [{"document_id": p.unit.document_id, "unit_id": p.unit.unit_id} for p in payloads]
        fields = [
            {
                "key": key,
                "title": title,
                "kind": kind,
                "description": title,
                "fields": [],
                "sources": sources,
            }
            for key, title, kind in [
                ("invoice_number", "Invoice number", "string"),
                ("total", "Printed total", "number"),
            ]
        ]
        if self.invalid:
            self.invalid -= 1
            fields[0]["sources"] = [{"document_id": "invented", "unit_id": "invented"}]
        return {
            "name": "Supplier invoice",
            "description": "Invoice identifier and total.",
            "fields": fields,
        }, usage


def seed_document(core, doc_id, count=1):
    core.job_repo.save_document(
        Document(
            document_id=doc_id,
            filename="synthetic.txt",
            media_type="application/pdf",
            sha256="0" * 64,
            bytes_size=100,
            storage_key=f"{doc_id}/original",
        )
    )
    units = []
    for i in range(count):
        ref = f"{doc_id}/text/{i}"
        core.blob_store.put_bytes(ref, b"Invoice number: TEST-001\nTotal: 120.00")
        units.append(
            DocumentUnit(
                unit_id=f"page_{i}",
                document_id=doc_id,
                ordinal=i,
                kind=UnitKind.PDF_PAGE,
                native_text_ref=ref,
            )
        )
    core.job_repo.save_units(doc_id, units)


@pytest.fixture
def discovery(tmp_path):
    models = DiscoveryModels()
    core = build_container(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{tmp_path / 'core.db'}",
            local_storage_root=tmp_path / "files",
            local_telemetry_root=tmp_path / "traces",
            openrouter_api_key="",
            api_key="",
        ),
        schema_decision_engine=models,
        schema_generation_engine=models,
        create_tables=True,
    )
    seed_document(core, "doc_one")
    seed_document(core, "doc_two", 10)
    return core, models, TestClient(create_app(core))


def test_suggestion_worker_compact_sources_and_idempotency(discovery):
    core, models, client = discovery
    body = {"document_ids": ["doc_one", "doc_two"]}
    response = client.post("/v1/schema-suggestions", json=body, headers={"Idempotency-Key": "same"})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert (
        client.post(
            "/v1/schema-suggestions", json=body, headers={"Idempotency-Key": "same"}
        ).json()["job_id"]
        == job_id
    )
    assert (
        client.post(
            "/v1/schema-suggestions",
            json={"document_ids": ["doc_one"]},
            headers={"Idempotency-Key": "same"},
        ).status_code
        == 409
    )
    assert asyncio.run(WorkerRunner(core).process_one_if_available()) == job_id
    result = client.get(f"/v1/schema-suggestions/{job_id}").json()
    assert result["status"] == "completed", result
    assert result["usage"]["llm_calls"] == 4
    assert result["usage"]["estimated_cost_usd"] == pytest.approx(0.004)
    assert result["result"]["coverage"][1]["partial"]
    assert result["result"]["coverage"][1]["inspected_units"] == ["page_0", "page_4", "page_9"]
    assert len(result["result"]["field_sources"]["/total"]) == 4
    assert "TEST-001" not in str(result["result"]["schema"])
    assert "checkpoints" not in result
    assert asyncio.run(WorkerRunner(core).process_one_if_available()) is None
    assert models.calls == ["unit_0", "compatibility", "generate", "field_0"]


@pytest.mark.parametrize("compatibility", ["DIFFERENT", "INSUFFICIENT"])
def test_incompatible_or_unknown_never_generates(discovery, compatibility):
    core, models, _ = discovery
    models.compatibility = compatibility
    job = core.suggestion_service.submit(["doc_one"])
    asyncio.run(WorkerRunner(core).process_one_if_available())
    result = core.suggestion_service.repo.get(job.job_id)
    assert result.status == "needs_review"
    assert "schema" not in result.result
    assert "generate" not in models.calls


def test_repair_bounded_and_unsupported_fields_visible(discovery):
    core, models, _ = discovery
    models.invalid = 1
    models.support = "UNSUPPORTED"
    job = core.suggestion_service.submit(["doc_one"])
    asyncio.run(WorkerRunner(core).process_one_if_available())
    result = core.suggestion_service.repo.get(job.job_id)
    assert result.status == "completed"
    assert models.calls.count("generate") == 2
    assert result.result["field_assessments"]["/total"]["choice"] == "UNSUPPORTED"
    assert result.result["warnings"]


def test_budget_cancel_and_request_fencing(discovery):
    core, models, client = discovery
    job = core.suggestion_service.submit(["doc_one"], max_cost_usd=0.0005)
    asyncio.run(WorkerRunner(core).process_one_if_available())
    result = core.suggestion_service.repo.get(job.job_id)
    assert result.status == "failed" and result.attempts == 1
    assert result.usage.estimated_cost_usd == 0.001
    cancelled = core.suggestion_service.submit(["doc_one"])
    assert (
        client.post(f"/v1/schema-suggestions/{cancelled.job_id}/cancel").json()["status"]
        == "cancelled"
    )
    assert asyncio.run(WorkerRunner(core).process_one_if_available()) is None
    assert (
        client.post(
            "/v1/schema-suggestions", json={"document_ids": ["doc_one", "doc_one"]}
        ).status_code
        == 400
    )
    assert (
        client.post("/v1/schema-suggestions", json={"document_ids": ["absent"]}).status_code == 404
    )


def test_crash_resume_checkpoints_and_old_owner_fenced(discovery):
    core, models, _ = discovery
    repo = core.suggestion_service.repo
    job = core.suggestion_service.submit(["doc_one"])

    async def interrupt():
        models.pause = asyncio.Event()
        task = asyncio.create_task(core.suggestion_service.process_one_if_available())
        await models.pause.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(interrupt())
    with repo.sessions.begin() as db:
        db.execute(
            update(SuggestionRow).values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    stale = repo.get(job.job_id)
    models.pause = None
    asyncio.run(core.suggestion_service.process_one_if_available())
    result = repo.get(job.job_id)
    assert result.status == "completed"
    assert models.calls.count("compatibility") == 1
    assert models.calls.count("unit_0") == 1
    assert result.attempts == 5
    assert result.usage.estimated_cost_usd == pytest.approx(0.005)
    with pytest.raises(Exception, match="lease"):
        repo.save(stale, "old-owner")


def test_compiler_rejects_bloat_duplicate_keys_and_invented_sources():
    field = {
        "key": "identifier",
        "kind": "string",
        "title": "Identifier",
        "description": "Identifier",
        "sources": [{"document_id": "d", "unit_id": "p"}],
    }
    proposal = SchemaProposal(name="Record", description="Record", fields=[field])
    schema, _ = compile_proposal(proposal, {("d", "p")})
    assert schema["properties"]["identifier"]["type"] == ["string", "null"]
    with pytest.raises(InvalidSchemaError):
        compile_proposal(proposal, set())
    doubled = proposal.model_copy(deep=True)
    doubled.fields += copy.deepcopy(doubled.fields)
    with pytest.raises(InvalidSchemaError, match="duplicate"):
        compile_proposal(doubled, {("d", "p")})


def test_generation_schema_is_accepted_by_actual_structured_output_adapter():
    import json

    from pydantic_ai import StructuredDict

    from ai_idp.adapters.outbound.openrouter.schema_client import proposal_output_schema

    schema = proposal_output_schema()
    assert "$ref" not in json.dumps(schema)
    assert "$defs" not in schema
    assert StructuredDict(schema, name="proposal")


def test_compiler_rejects_more_than_twenty_leaves():
    leaf = {
        "key": "identifier",
        "title": "Identifier",
        "description": "Identifier",
        "kind": "string",
        "sources": [{"document_id": "d", "unit_id": "p"}],
    }
    groups = [
        {
            "key": f"group_{i}",
            "title": "Group",
            "description": "Group",
            "kind": "object",
            "fields": [{**leaf, "key": f"field_{j}"} for j in range(8)],
        }
        for i in range(3)
    ]
    proposal = SchemaProposal(name="Record", description="Record", fields=groups)
    with pytest.raises(InvalidSchemaError, match="20"):
        compile_proposal(proposal, {("d", "p")})


def test_discovery_migration_upgrade_downgrade_upgrade(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    url = f"sqlite:///{tmp_path / 'migration.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    assert "schema_suggestion_jobs" in inspect(engine).get_table_names()
    command.downgrade(cfg, "0003_model_limits")
    assert "schema_suggestion_jobs" not in inspect(engine).get_table_names()
    command.upgrade(cfg, "head")
    assert "schema_suggestion_jobs" in inspect(engine).get_table_names()
    engine.dispose()


def test_cancellation_preserves_late_reported_cost_without_resurrecting_job(discovery):
    core, _, _ = discovery
    repo = core.suggestion_service.repo
    job = core.suggestion_service.submit(["doc_one"])
    claimed = repo.claim("owner", 120)
    repo.reserve_request(job.job_id, "owner", 12)
    repo.cancel(job.job_id)
    claimed.usage.estimated_cost_usd = 0.001
    claimed.status = "completed"
    repo.save(claimed, "owner")
    saved = repo.get(job.job_id)
    assert saved.status == "cancelled"
    assert saved.usage.estimated_cost_usd == 0.001
    assert saved.attempts == 1
    assert core.suggestion_service.public_view(saved)["result"] is None


def test_suggestions_and_extractions_share_global_job_capacity(discovery):
    core, _, client = discovery
    core.job_repo._max_concurrent_jobs = 1
    repo = core.suggestion_service.repo
    repo.max_concurrent_jobs = 1
    suggestion = core.suggestion_service.submit(["doc_one"])
    extraction = client.post(
        "/v1/extractions",
        json={
            "document_id": "doc_one",
            "schema": {
                "type": "object",
                "properties": {"identifier": {"type": "string"}},
            },
        },
    ).json()
    claimed = repo.claim("suggestion-owner", 120)
    assert claimed.job_id == suggestion.job_id
    assert core.job_repo.claim_job(extraction["job_id"], "extract-owner", 120) is None
    repo.cancel(suggestion.job_id)
    assert core.job_repo.claim_job(extraction["job_id"], "extract-owner", 120)
    core.suggestion_service.submit(["doc_one"])
    assert repo.claim("second-suggestion", 120) is None
