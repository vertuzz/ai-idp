"""Opt-in, USD 0.10 estimated-budget smoke test using only synthetic workbook data."""

import os

import pytest

from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.settings import Settings
from scripts.generate_spreadsheet_fixture import workbook_bytes
from tests.integration.test_spreadsheet_pages import SCHEMA


@pytest.mark.skipif(
    os.environ.get("AI_IDP_RUN_LIVE_REVIEW") != "1", reason="Opt-in paid model smoke test"
)
async def test_live_nested_workbook_continuation_and_evidence(tmp_path):
    core = build_container(
        Settings(
            _env_file=".env",
            database_url=f"sqlite:///{tmp_path.as_posix()}/core.db",
            local_storage_root=tmp_path / "files",
            local_telemetry_root=tmp_path / "traces",
            max_job_estimated_cost_usd=0.10,
            max_model_calls=64,
            max_job_seconds=180,
            max_output_tokens=2048,
            extraction_page_items=3,
            max_provider_retries=0,
            max_field_extra_attempts=0,
            max_coverage_reviews=0,
            max_parallel_decision_batches=1,
        ),
        create_tables=True,
    )
    document = core.ingest_use_case.execute(
        raw_bytes=workbook_bytes(12, 2), filename="synthetic.xlsx"
    )
    job = core.request_extraction_use_case.execute(
        document_id=document.document_id,
        schema_json={"type": "object", "properties": {"payload": SCHEMA}, "required": ["payload"]},
    )
    result = await core.pipeline_service.execute_job(job.job_id)
    assert result.data == {
        "payload": {"items": [{"id": f"LOT-{i:06d}", "amount": (i + 1) * 1.25} for i in range(12)]}
    }
    assert result.schema_valid
    assert all(result.fields[f"/payload/items/{i}/id"].sources for i in range(12))
    print(f"Recorded estimated smoke cost: ${result.usage.estimated_cost_usd:.6f}")
