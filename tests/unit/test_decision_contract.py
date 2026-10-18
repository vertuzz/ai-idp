import json
from unittest.mock import AsyncMock

import pytest

from ai_idp.adapters.outbound.openrouter.decisions_client import (
    OpenRouterDecisionEngine,
    _build_unit_state,
    _parse_choice_answer,
    _parse_noul_answer,
)
from ai_idp.adapters.outbound.openrouter.extraction_client import build_extraction_envelope_schema
from ai_idp.application.ports.protocols import UnitInputPayload
from ai_idp.domain.enums import UnitKind
from ai_idp.domain.errors import ProviderError
from ai_idp.domain.models import DocumentUnit, Evidence
from ai_idp.domain.schema_normalizer import normalize_extraction_schema

OPTIONS = ["SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"]


@pytest.mark.parametrize(
    "answer",
    [
        None,
        {},
        "SUPPORTED",
        {"choice": "unknown"},
        {"probabilities": {"SUPPORTED": 1}},
        {"probabilities": dict(zip(OPTIONS, [float("nan"), 0, 0], strict=True))},
        {"probabilities": dict(zip(OPTIONS, [1, 1, 0], strict=True))},
    ],
)
def test_invalid_choice_never_defaults_to_supported(answer):
    with pytest.raises(ProviderError):
        _parse_choice_answer(answer, OPTIONS)


@pytest.mark.parametrize(
    "answer",
    [None, {}, True, -0.1, 1.1, float("inf"), {"probabilities": {"true": 0.8, "false": 0.8}}],
)
def test_invalid_relevance_is_not_an_invented_probability(answer):
    with pytest.raises(ProviderError):
        _parse_noul_answer(answer)


def test_explicit_choice_does_not_fabricate_a_probability_vector():
    assert _parse_choice_answer({"choice": "SUPPORTED"}, OPTIONS) == ("SUPPORTED", {})


def test_unit_state_preserves_long_text_context_and_all_images():
    payload = UnitInputPayload(
        unit=DocumentUnit(unit_id="u", document_id="d", ordinal=1, kind=UnitKind.DOCX_BLOCK),
        native_text="x" * 20000 + "TEXT_TAIL",
        document_context="y" * 20000 + "CONTEXT_TAIL",
        image_bytes=b"first",
        additional_images=[(b"second", "image/jpeg")],
    )
    state = _build_unit_state(payload)
    assert "TEXT_TAIL" in state[0] and "CONTEXT_TAIL" in state[0]
    assert len(state) == 3
    assert state[2]["image_url"]["url"].startswith("data:image/jpeg;")


async def test_verifier_gets_complete_candidate_all_sources_and_citations():
    engine = OpenRouterDecisionEngine(api_key="unused")
    engine._post_decisions = AsyncMock(
        return_value=(
            {
                "answers": {
                    "verify_0": {"probabilities": dict(zip(OPTIONS, [0.1, 0.8, 0.1], strict=True))}
                }
            },
            1,
        )
    )
    spec = normalize_extraction_schema(
        {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}}}
    )
    payloads = {
        name: UnitInputPayload(
            unit=DocumentUnit(unit_id=name, document_id="d", ordinal=i, kind=UnitKind.PDF_PAGE),
            native_text="source " + name,
        )
        for i, name in enumerate(["cited", "uncited"], start=1)
    }
    value = ["a" * 2000, "WRONG_TAIL"]
    await engine.verify_fields(
        "j",
        [(spec.fields[0], value, [Evidence(unit_id="cited", quote="q" * 700)])],
        payloads,
        "model",
    )
    _, state, questions = engine._post_decisions.call_args.args
    assert any("source uncited" in str(part) for part in state)
    instruction = questions["verify_0"]["instructions"]
    assert json.dumps(value) in instruction
    assert "q" * 700 in instruction


async def test_missing_verification_answer_fails_closed():
    engine = OpenRouterDecisionEngine(api_key="unused")
    engine._post_decisions = AsyncMock(return_value=({"answers": {}}, 1))
    spec = normalize_extraction_schema({"type": "object", "properties": {"id": {"type": "string"}}})
    with pytest.raises(ProviderError):
        await engine.verify_fields("j", [(spec.fields[0], "invented", [])], {}, "model")


async def test_relevance_batch_scores_units_against_all_fields_without_pair_expansion():
    engine = OpenRouterDecisionEngine(api_key="unused")
    engine._post_decisions = AsyncMock(
        return_value=({"answers": {f"unit_{i}": 0.9 if i % 2 else 0.1 for i in range(8)}}, 7)
    )
    spec = normalize_extraction_schema(
        {
            "type": "object",
            "properties": {
                f"target_{i}": {"type": "string", "description": f"DESCRIPTION_{i}_TAIL"}
                for i in range(80)
            },
            "required": [f"target_{i}" for i in range(40)],
        }
    )
    payloads = [
        UnitInputPayload(
            unit=DocumentUnit(
                unit_id=f"page_{i}",
                document_id="d",
                ordinal=i + 1,
                kind=UnitKind.PDF_PAGE,
                source_locator={"page_number": i + 1},
            ),
            native_text=f"page {i} text " + "x" * 20000 + "TEXT_TAIL",
            image_bytes=f"image {i}".encode(),
            document_context="OUTSIDE_BATCH_CONTEXT",
            prev_excerpt="OUTSIDE_NEIGHBOR",
        )
        for i in range(8)
    ]
    result = await engine.score_relevance_batch("j", payloads, spec.fields, "guidance", "m")
    _, state, questions = engine._post_decisions.call_args.args
    assert len(questions) == 8  # Not 8 * 80 field questions.
    assert len([part for part in state if isinstance(part, dict)]) == 8
    assert "OUTSIDE_BATCH_CONTEXT" not in str(state) and "OUTSIDE_NEIGHBOR" not in str(state)
    assert str(state).count("TEXT_TAIL") == 8
    targets = json.loads(state[1].split("\n", 1)[1])
    assert len(targets) == 80
    assert sum(target["required"] for target in targets) == 40
    assert targets[-1]["description"] == "DESCRIPTION_79_TAIL"
    assert all("AT LEAST ONE" in q["instructions"] for q in questions.values())
    assert '"page_7"' in questions["unit_7"]["instructions"]
    assert [r.score for r in result.results.values()] == [0.1, 0.9] * 4
    assert all(r.raw_distribution["true"] == r.score for r in result.results.values())
    records = [d for r in result.results.values() for d in r.decision_records]
    assert len(records) == 8 and all(d.field_path is None for d in records)
    assert result.usage.call_count == 1
    engine._post_decisions.return_value = ({"answers": {"unit_0": 0.9}}, 7)
    with pytest.raises(ProviderError):
        await engine.score_relevance_batch("j", payloads, spec.fields, "guidance", "m")


def test_missing_enum_and_const_values_fit_internal_envelope():
    import jsonschema

    for prop in ({"type": "string", "enum": ["yes", "no"]}, {"type": "string", "const": "yes"}):
        spec = normalize_extraction_schema({"type": "object", "properties": {"answer": prop}})
        envelope = build_extraction_envelope_schema(spec.fields)
        jsonschema.validate({"answer": None, "_evidence": []}, envelope)


async def test_extractor_preserves_full_text_and_every_image(monkeypatch):
    from types import SimpleNamespace

    from ai_idp.adapters.outbound.openrouter import extraction_client as module

    sent = []

    class Agent:
        def __init__(self, **kwargs):
            pass

        async def run(self, parts):
            sent.extend(parts)
            return SimpleNamespace(output={"id": "value", "_evidence": []}, usage=lambda: None)

    monkeypatch.setattr(module, "Agent", Agent)
    monkeypatch.setattr(module, "OpenAIChatModel", lambda *args, **kwargs: None)
    engine = module.PydanticAIExtractionEngine(api_key="unused")
    monkeypatch.setattr(engine, "_build_provider", lambda client=None: None)
    spec = normalize_extraction_schema({"type": "object", "properties": {"id": {"type": "string"}}})
    payload = UnitInputPayload(
        unit=DocumentUnit(unit_id="u", document_id="d", ordinal=1, kind=UnitKind.DOCX_BLOCK),
        native_text="a" * 20000 + "TAIL",
        image_bytes=b"one",
        additional_images=[(b"two", "image/png")],
    )
    from ai_idp.domain.enums import Modality

    await engine.extract_fields(
        "j", spec, spec.fields, [(payload, Modality.TEXT_AND_VISION)], "model"
    )
    assert any(isinstance(p, str) and "TAIL" in p for p in sent)
    assert [p.data for p in sent if isinstance(p, module.BinaryContent)] == [b"one", b"two"]


async def test_image_limits_count_all_embedded_images_without_dropping_units():
    from ai_idp.application.services.batching import unit_batches
    from ai_idp.domain.enums import Modality
    from ai_idp.domain.errors import ModelInputLimitExceededError

    inputs = [
        (
            UnitInputPayload(
                unit=DocumentUnit(
                    unit_id=f"u{i}", document_id="d", ordinal=i + 1, kind=UnitKind.DOCX_BLOCK
                ),
                image_bytes=b"one",
                additional_images=[(b"two", "image/png")],
            ),
            Modality.TEXT_AND_VISION,
        )
        for i in range(10)
    ]
    batches = unit_batches(inputs, max_units=12, max_bytes=1_000_000, max_images=8)
    assert [len(b) for b in batches] == [4, 4, 2]
    assert [p.unit.unit_id for b in batches for p, _ in b] == [f"u{i}" for i in range(10)]
    inputs[0][0].additional_images = [(b"image", "image/png")] * 8
    with pytest.raises(ModelInputLimitExceededError):
        unit_batches(inputs, max_units=12, max_bytes=1_000_000, max_images=8)
    engine = OpenRouterDecisionEngine(api_key="unused", max_images=8)
    with pytest.raises(ModelInputLimitExceededError):
        await engine._post_decisions("model", [{"type": "image_url"}] * 9, {})
