from unittest.mock import AsyncMock, Mock

import pytest
from pydantic_ai import BinaryContent

from ai_idp.adapters.outbound.openrouter.relevance_client import GenerativeRelevanceEngine
from ai_idp.application.ports.protocols import UnitInputPayload
from ai_idp.application.services.pipeline import ExtractionPipelineService
from ai_idp.domain.enums import UnitKind
from ai_idp.domain.errors import ProviderError
from ai_idp.domain.models import DocumentUnit, UsageRecord
from ai_idp.domain.schema_normalizer import normalize_extraction_schema


@pytest.mark.parametrize(
    "flags,valid",
    [
        ({"/title": True, "/amount": False}, True),
        ({"/title": None, "/amount": False}, True),
        ({"/title": True}, False),
        ({"/title": "true", "/amount": False}, False),
        ({"/title": 1, "/amount": False}, False),
        ({"page_1": {"/title": True, "/amount": False}}, False),
    ],
)
async def test_single_unit_flat_schema_validation_and_payload_handling(flags, valid):
    client = AsyncMock()
    usage = UsageRecord(usage_id="u", job_id="j", stage="scoring_relevance", model_id="m")
    client.run_structured.return_value = (flags, usage)
    engine = GenerativeRelevanceEngine(client)
    spec = normalize_extraction_schema(
        {
            "type": "object",
            "properties": {"title": {"type": "string"}, "amount": {"type": "number"}},
        }
    )
    payload = UnitInputPayload(
        unit=DocumentUnit(unit_id="page_1", document_id="d", ordinal=1, kind=UnitKind.PDF_PAGE),
        native_text="t" * 20000 + "TEXT_TAIL",
        document_context="ctx" * 20000 + "CONTEXT_TAIL",
        image_bytes=b"one",
        additional_images=[(b"two", "image/png")],
    )
    if not valid:
        with pytest.raises(ProviderError):
            await engine.score_relevance_batch("j", [payload], spec.fields, "guidance", "m")
        return
    result = await engine.score_relevance_batch("j", [payload], spec.fields, "guidance", "m")
    page = result.results["page_1"]
    assert page.field_scores == {"/title": 1.0, "/amount": 0.0}
    assert page.raw_distributions == {}
    assert page.decision_records[0].scores == {}
    assert page.decision_records[0].selected == {"relevant": flags["/title"], "retained": True}
    parts = client.run_structured.call_args.kwargs["user_parts"]
    assert str(parts).count("CONTEXT_TAIL") == 1
    assert any(isinstance(p, str) and "TEXT_TAIL" in p for p in parts)
    assert [p.data for p in parts if isinstance(p, BinaryContent)] == [b"one", b"two"]
    assert result.usage is usage

    schema = client.run_structured.call_args.kwargs["schema"]
    assert set(schema["properties"].keys()) == {"/title", "/amount"}


async def test_single_unit_without_document_context_uses_neighbor_excerpts():
    client = AsyncMock()
    usage = UsageRecord(usage_id="u", job_id="j", stage="scoring_relevance", model_id="m")
    client.run_structured.return_value = ({"/title": True}, usage)
    engine = GenerativeRelevanceEngine(client)
    spec = normalize_extraction_schema(
        {"type": "object", "properties": {"title": {"type": "string"}}}
    )
    payload = UnitInputPayload(
        unit=DocumentUnit(unit_id="page_1", document_id="d", ordinal=1, kind=UnitKind.PDF_PAGE),
        native_text="page 1 content",
        prev_excerpt="prev page excerpt",
        next_excerpt="next page excerpt",
        document_context="",
    )
    result = await engine.score_relevance_batch("j", [payload], spec.fields, "guidance", "m")
    assert result.results["page_1"].field_scores == {"/title": 1.0}
    parts = client.run_structured.call_args.kwargs["user_parts"]
    assert not any("Full document context:" in str(p) for p in parts)
    assert any(
        "Neighbor context only:\nprev page excerpt\nnext page excerpt" in str(p) for p in parts
    )


async def test_multi_unit_nested_matrix_schema():
    client = AsyncMock()
    usage = UsageRecord(usage_id="u", job_id="j", stage="scoring_relevance", model_id="m")
    response_matrix = {
        "page_1": {"/title": True, "/amount": False},
        "page_2": {"/title": False, "/amount": True},
    }
    client.run_structured.return_value = (response_matrix, usage)
    engine = GenerativeRelevanceEngine(client)
    spec = normalize_extraction_schema(
        {
            "type": "object",
            "properties": {"title": {"type": "string"}, "amount": {"type": "number"}},
        }
    )
    payload_1 = UnitInputPayload(
        unit=DocumentUnit(unit_id="page_1", document_id="d", ordinal=1, kind=UnitKind.PDF_PAGE),
        native_text="page 1 text",
    )
    payload_2 = UnitInputPayload(
        unit=DocumentUnit(unit_id="page_2", document_id="d", ordinal=2, kind=UnitKind.PDF_PAGE),
        native_text="page 2 text",
    )
    result = await engine.score_relevance_batch(
        "j", [payload_1, payload_2], spec.fields, "guidance", "m"
    )
    assert set(result.results.keys()) == {"page_1", "page_2"}
    assert result.results["page_1"].field_scores == {"/title": 1.0, "/amount": 0.0}
    assert result.results["page_2"].field_scores == {"/title": 0.0, "/amount": 1.0}

    schema = client.run_structured.call_args.kwargs["schema"]
    assert set(schema["properties"].keys()) == {"page_1", "page_2"}
    assert set(schema["properties"]["page_1"]["properties"].keys()) == {"/title", "/amount"}


async def test_multi_unit_rejects_missing_unit_or_flat_response():
    client = AsyncMock()
    usage = UsageRecord(usage_id="u", job_id="j", stage="scoring_relevance", model_id="m")
    client.run_structured.return_value = ({"page_1": {"/title": True, "/amount": False}}, usage)
    engine = GenerativeRelevanceEngine(client)
    spec = normalize_extraction_schema(
        {
            "type": "object",
            "properties": {"title": {"type": "string"}, "amount": {"type": "number"}},
        }
    )
    payload_1 = UnitInputPayload(
        unit=DocumentUnit(unit_id="page_1", document_id="d", ordinal=1, kind=UnitKind.PDF_PAGE),
        native_text="page 1 text",
    )
    payload_2 = UnitInputPayload(
        unit=DocumentUnit(unit_id="page_2", document_id="d", ordinal=2, kind=UnitKind.PDF_PAGE),
        native_text="page 2 text",
    )
    with pytest.raises(ProviderError):
        await engine.score_relevance_batch(
            "j", [payload_1, payload_2], spec.fields, "guidance", "m"
        )


def test_load_unit_payloads_leaves_document_context_empty():
    blob_store = Mock()
    blob_store.get_size.return_value = 100
    blob_store.get_text.side_effect = lambda ref: f"Text for {ref}"
    blob_store.get_bytes.return_value = b"image_data"
    service = ExtractionPipelineService(
        blob_store=blob_store,
        document_reader=Mock(),
        decision_engine=Mock(),
        extraction_engine=Mock(),
        job_repo=Mock(),
        result_repo=Mock(),
        telemetry=Mock(),
    )
    units = [
        DocumentUnit(
            unit_id=f"page_{i}",
            document_id="doc_1",
            ordinal=i,
            kind=UnitKind.PDF_PAGE,
            source_locator={"page": i},
            native_text_ref=f"text_ref_{i}",
            image_ref=f"image_ref_{i}.png",
        )
        for i in range(1, 4)
    ]
    payloads = service._load_unit_payloads(units, instructions="Extract details")
    assert len(payloads) == 3
    for p in payloads:
        assert p.document_context == ""
        assert p.extraction_instructions == "Extract details"
    assert payloads[0].native_text == "Text for text_ref_1"
    assert payloads[0].prev_excerpt is None
    assert payloads[0].next_excerpt == "Text for text_ref_2"
    assert payloads[1].prev_excerpt == "Text for text_ref_1"
    assert payloads[1].next_excerpt == "Text for text_ref_3"
    assert payloads[2].prev_excerpt == "Text for text_ref_2"
    assert payloads[2].next_excerpt is None
