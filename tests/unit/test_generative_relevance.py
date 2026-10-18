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
        ({"page_1": True, "page_2": False}, True),
        ({"page_1": None, "page_2": False}, True),
        ({"page_1": True}, False),
        ({"page_1": "true", "page_2": False}, False),
        ({"page_1": 1, "page_2": False}, False),
        ({"page_1": {"/title": True}, "page_2": False}, False),
        ({"page_1": True, "page_2": False, "unknown": True}, False),
    ],
)
async def test_complete_unit_flags_preserve_all_fields_text_and_images(flags, valid):
    client = AsyncMock()
    usage = UsageRecord(usage_id="u", job_id="j", stage="scoring_relevance", model_id="m")
    client.run_structured.return_value = (flags, usage)
    engine = GenerativeRelevanceEngine(client)
    spec = normalize_extraction_schema(
        {
            "type": "object",
            "properties": {
                f"target_{i}": {"type": "string", "description": f"DESCRIPTION_{i}_TAIL"}
                for i in range(80)
            },
        }
    )
    payloads = [
        UnitInputPayload(
            unit=DocumentUnit(
                unit_id=f"page_{i}", document_id="d", ordinal=i, kind=UnitKind.PDF_PAGE
            ),
            native_text="t" * 20000 + "TEXT_TAIL",
            document_context="OUTSIDE_CONTEXT_TAIL",
            prev_excerpt="OUTSIDE_NEIGHBOR",
            image_bytes=b"one",
            additional_images=[(b"two", "image/png")],
        )
        for i in (1, 2)
    ]
    if not valid:
        with pytest.raises(ProviderError):
            await engine.score_relevance_batch("j", payloads, spec.fields, "guidance", "m")
        return
    result = await engine.score_relevance_batch("j", payloads, spec.fields, "guidance", "m")
    page = result.results["page_1"]
    assert page.score == 1.0
    assert result.results["page_2"].score == 0.0
    assert page.raw_distribution == {}
    assert page.decision_records[0].scores == {}
    assert page.decision_records[0].field_path is None
    assert page.decision_records[0].selected == {"relevant": flags["page_1"], "retained": True}
    sent = client.run_structured.call_args.kwargs
    assert "DESCRIPTION_79_TAIL" in sent["system_instructions"]
    parts = sent["user_parts"]
    assert "OUTSIDE_CONTEXT_TAIL" not in str(parts) and "OUTSIDE_NEIGHBOR" not in str(parts)
    assert str(parts).count("TEXT_TAIL") == 2
    assert [p.data for p in parts if isinstance(p, BinaryContent)] == [b"one", b"two"] * 2
    assert result.usage is usage
    assert set(sent["schema"]["properties"]) == {"page_1", "page_2"}


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
