import uuid

from fastapi.testclient import TestClient

from ai_idp.adapters.inbound.http.app import create_app
from ai_idp.application.ports.protocols import ExtractionBatchResult
from ai_idp.domain.enums import VerificationStatus
from ai_idp.domain.models import Evidence, UsageRecord
from tests.integration.test_api_and_worker import FakeDecisionEngine
from tests.integration.test_pipeline_recovery import setup


class NestedExtractor:
    async def extract_fields(self, **kw):
        values = {
            "customer": {"name": "Example", "tax_id": None},
            "items": [{"price": 12}, {"price": 15}],
        }
        data = {f.name: values.get(f.name, "RECOVERED") for f in kw["target_fields"]}
        return ExtractionBatchResult(
            data=data,
            evidence_by_field={
                path: [Evidence(unit_id=kw["unit_inputs"][0][0].unit.unit_id, quote=str(value))]
                for path, value in (
                    ("/customer/name", "Example"),
                    ("/customer/tax_id", None),
                    ("/items/0/price", 12),
                    ("/items/1/price", 15),
                    ("/items", values["items"]),
                    ("/customer", values["customer"]),
                )
            },
            model_id=kw["model_id"],
            usage=UsageRecord(
                usage_id=uuid.uuid4().hex,
                job_id=kw["job_id"],
                stage=kw["stage_name"],
                model_id=kw["model_id"],
            ),
        )


async def test_nested_leaf_diagnostics_persist_and_http_attempts_are_visible(tmp_path):
    c, doc, _ = setup(tmp_path, extractor=NestedExtractor(), max_field_extra_attempts=0)
    job = c.request_extraction_use_case.execute(
        document_id=doc.document_id,
        schema_json={
            "type": "object",
            "properties": {
                "customer": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "tax_id": {"type": "string"}},
                    "required": ["name", "tax_id"],
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"price": {"type": "number"}},
                        "required": ["price"],
                    },
                },
            },
            "required": ["customer", "items"],
        },
    )
    result = await c.pipeline_service.execute_job(job.job_id)
    assert result.data["items"][1]["price"] == 15
    assert result.fields["/items/1/price"].sources[0].quote == "15"
    assert result.fields["/items/0/price"].verification == VerificationStatus.SUPPORTED
    assert "/customer/tax_id" in result.unresolved_fields
    assert not result.schema_valid
    assert result.schema_errors
    response = TestClient(create_app(c)).get(f"/v1/extractions/{job.job_id}/result").json()
    assert response["fields"]["/items/1/price"]["attempts"][0]["model_id"]
    assert response["schema_errors"]


async def test_schema_valid_is_independent_from_verification(tmp_path):
    c, _, job = setup(
        tmp_path,
        decision=FakeDecisionEngine(contradict_first_attempt_for={"/record_id"}),
        max_field_extra_attempts=0,
    )
    result = await c.pipeline_service.execute_job(job.job_id)
    assert result.schema_valid
    assert result.unresolved_fields == ["/record_id"]
