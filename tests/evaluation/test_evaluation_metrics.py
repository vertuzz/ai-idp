from __future__ import annotations

from ai_idp.domain.enums import FieldStatus, JobStatus, VerificationStatus
from ai_idp.domain.models import Evidence, ExtractionResult, FieldValue, UsageSummary
from ai_idp.evaluation.metrics import (
    evidence_matches,
    resolve_json_pointer,
    score_extraction_result,
    values_match,
)


def test_resolve_json_pointer_and_value_matching():
    payload = {
        "total_price": "1,591,600",
        "items": [
            {"name": "Nasi Campur Bali", "quantity": "1", "price": "75,000"},
        ],
    }
    found, val = resolve_json_pointer(payload, "/items/0/name")
    assert found is True
    assert val == "Nasi Campur Bali"

    exact, norm = values_match("1", "1 x")
    assert exact is False
    assert norm is True

    exact2, norm2 = values_match("1,591,600", "1,591,600")
    assert exact2 is True
    assert norm2 is True


def test_score_extraction_result_tracks_false_supported_and_evidence():
    result = ExtractionResult(
        job_id="job_eval_1",
        status=JobStatus.COMPLETED,
        data={"record_id": "WRONG-ID", "net_total": 1200},
        schema_valid=True,
        fields={
            "/record_id": FieldValue(
                path="/record_id",
                value="WRONG-ID",
                status=FieldStatus.VERIFIED,
                verification=VerificationStatus.SUPPORTED,
                sources=[Evidence(unit_id="page_000001", locator={"page_number": 1})],
            ),
            "/net_total": FieldValue(
                path="/net_total",
                value=1200,
                status=FieldStatus.VERIFIED,
                verification=VerificationStatus.SUPPORTED,
                sources=[Evidence(unit_id="page_000001", locator={"page_number": 1})],
            ),
        },
        usage=UsageSummary(llm_calls=4, estimated_cost_usd=0.0005),
    )
    expected = [
        {
            "path": "/record_id",
            "value": "TEST-NATIVE-01",
            "sources": [{"unit_id": "page_000001", "locator": {"page_number": 1}}],
        },
        {
            "path": "/net_total",
            "value": 1200,
            "sources": [{"unit_id": "page_000001", "locator": {"page_number": 1}}],
        },
    ]
    summary = score_extraction_result(
        case_id="synthetic-native-01",
        source="synthetic",
        doc_format="pdf",
        split="development",
        model_profile="default",
        result=result,
        expected_fields=expected,
    )
    assert summary.fields_total == 2
    assert summary.exact_matches == 1
    assert summary.evidence_matches == 2
    assert summary.false_supported_count == 1
    assert evidence_matches(
        [Evidence(unit_id="block_000002", locator={"heading": "Current period summary"})],
        [{"locator": {"heading": "Current period summary"}}],
    )
