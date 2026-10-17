from __future__ import annotations

import asyncio
import copy
import json
import os
import time
import uuid
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent, BinaryContent, StructuredDict
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from ai_idp.adapters.outbound.openrouter.pricing import estimate_cost_usd
from ai_idp.application.ports.protocols import ExtractionBatchResult, UnitInputPayload
from ai_idp.domain.enums import Modality
from ai_idp.domain.errors import ProviderError
from ai_idp.domain.models import (
    Evidence,
    ExtractionSpecification,
    TargetFieldSpec,
    UsageRecord,
)


def _make_nullable_property(prop_schema: dict[str, Any]) -> dict[str, Any]:
    cloned = copy.deepcopy(prop_schema)
    raw_type = cloned.get("type")
    if isinstance(raw_type, str) and raw_type != "null":
        cloned["type"] = [raw_type, "null"]
    elif isinstance(raw_type, list) and "null" not in raw_type:
        cloned["type"] = [*raw_type, "null"]
    if isinstance(cloned.get("properties"), dict):
        cloned.setdefault("additionalProperties", False)
    if isinstance(cloned.get("items"), dict) and cloned["items"].get("type") == "object":
        cloned["items"].setdefault("additionalProperties", False)
    if "enum" in cloned and None not in cloned["enum"]:
        cloned["enum"].append(None)
    if "const" in cloned:
        return {"anyOf": [cloned, {"type": "null"}]}
    return cloned


def build_extraction_envelope_schema(target_fields: list[TargetFieldSpec]) -> dict[str, Any]:
    """Build an internal JSON Schema envelope with nullable fields and _evidence citations."""
    properties: dict[str, Any] = {}
    required_names: list[str] = []
    for f in target_fields:
        properties[f.name] = _make_nullable_property(f.raw_schema)
        required_names.append(f.name)

    properties["_evidence"] = {
        "type": "array",
        "description": "One or more source citations for each populated non-null field.",
        "items": {
            "type": "object",
            "properties": {
                "field_path": {
                    "type": "string",
                    "description": (
                        "JSON pointer path of the field, e.g. '/total_price' or '/record_id'."
                    ),
                },
                "unit_id": {
                    "type": "string",
                    "description": (
                        "Exact Document Unit ID where the value appears, "
                        "e.g. 'page_000001', 'block_000001', or 'frame_000001'."
                    ),
                },
                "quote": {
                    "type": ["string", "null"],
                    "description": (
                        "Short verbatim excerpt from the source unit supporting the value."
                    ),
                },
            },
            "required": ["field_path", "unit_id", "quote"],
            "additionalProperties": False,
        },
    }
    required_names.append("_evidence")

    return {
        "type": "object",
        "title": "extraction_envelope",
        "properties": properties,
        "required": required_names,
        "additionalProperties": False,
    }


def _try_parse_json_string(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return None
    for candidate in (text, f"{{{text}}}", text.rstrip("}")):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _unpack_envelope_output(
    output_dict: dict[str, Any],
    target_fields: list[TargetFieldSpec],
) -> tuple[dict[str, Any], list[Any]]:
    raw_evidence = output_dict.get("_evidence") or output_dict.get("evidence")
    extracted_data: dict[str, Any] = {}

    if isinstance(output_dict.get("data"), dict):
        extracted_data = dict(output_dict["data"])
    elif isinstance(output_dict.get("data"), str):
        parsed = _try_parse_json_string(output_dict["data"])
        if isinstance(parsed, dict):
            extracted_data = parsed

    for f in target_fields:
        if f.name in output_dict:
            extracted_data[f.name] = output_dict[f.name]

    # Coerce stringified arrays/objects or scalar types if needed
    for f in target_fields:
        val = extracted_data.get(f.name)
        if isinstance(val, str) and f.field_type in ("array", "object"):
            parsed_field = _try_parse_json_string(val)
            if isinstance(parsed_field, (list, dict)):
                extracted_data[f.name] = parsed_field
        elif isinstance(val, str) and f.field_type == "integer":
            cleaned = val.replace(",", "").strip()
            if cleaned.lstrip("-").isdigit():
                extracted_data[f.name] = int(cleaned)
        elif isinstance(val, str) and f.field_type == "number":
            cleaned = val.replace(",", "").strip()
            try:
                extracted_data[f.name] = float(cleaned)
            except ValueError:
                pass

    if isinstance(raw_evidence, str):
        parsed_ev = _try_parse_json_string(raw_evidence)
        if isinstance(parsed_ev, list):
            raw_evidence = parsed_ev

    return extracted_data, raw_evidence if isinstance(raw_evidence, list) else []


class PydanticAIExtractionEngine:
    """Generative structured extraction adapter using Pydantic AI over OpenRouter."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://openrouter.ai/api",
        max_concurrent_requests: int = 6,
        max_retries: int = 2,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._semaphore = semaphore or asyncio.Semaphore(max_concurrent_requests)

    def _build_provider(self) -> OpenAIProvider:
        v1_url = self._base_url if self._base_url.endswith("/v1") else f"{self._base_url}/v1"
        return OpenAIProvider(base_url=v1_url, api_key=self._api_key)

    async def extract_fields(
        self,
        job_id: str,
        spec: ExtractionSpecification,
        target_fields: list[TargetFieldSpec],
        unit_inputs: list[tuple[UnitInputPayload, Modality]],
        model_id: str,
        stage_name: str = "extracting",
    ) -> ExtractionBatchResult:
        if not self._api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured.")
        if not target_fields or not unit_inputs:
            return ExtractionBatchResult(model_id=model_id)

        envelope_schema = build_extraction_envelope_schema(target_fields)
        field_lines = [
            f"- {f.path} (name='{f.name}', type={f.field_type}): "
            f"{f.description or 'Extract as written.'}"
            for f in target_fields
        ]
        caller_guidance = spec.instructions or "Extract values faithfully as written."
        system_instructions = (
            "You are a precise document data extraction engine.\n"
            "Extract the requested fields strictly from the provided document units.\n"
            "Rules:\n"
            "1. Never invent, guess, or fabricate values unsupported by the source units.\n"
            "2. If a field value is absent in the document units, return null for that field.\n"
            "3. Preserve exact printed formatting (including quantity prefixes/suffixes "
            "like '1 x' if printed on receipts).\n"
            "4. For every non-null extracted field, provide at least one item in '_evidence' "
            "with the exact 'field_path' (starting with '/'), the exact 'unit_id' "
            "(e.g. 'page_000001', 'block_000001', 'frame_000001'), and a verbatim 'quote'.\n"
            f"5. Caller instructions: {caller_guidance}\n"
            "Target fields:\n" + "\n".join(field_lines)
        )

        user_parts: list[Any] = [
            "Extract the target fields and evidence from the following document unit(s):"
        ]
        for payload, modality in unit_inputs:
            u = payload.unit
            loc_str = json.dumps(u.source_locator, ensure_ascii=False)
            unit_header = (
                f"\n--- Document Unit: {u.unit_id} "
                f"(kind={u.kind.value}, locator={loc_str}, "
                f"modality={modality.value}) ---"
            )
            user_parts.append(unit_header)
            if modality in (Modality.TEXT, Modality.TEXT_AND_VISION) and payload.native_text:
                user_parts.append(f"Unit Text ({u.unit_id}):\n{payload.native_text}")
            elif modality == Modality.TEXT and not payload.native_text:
                user_parts.append(f"Unit Text ({u.unit_id}): <no native text available>")

            if modality in (Modality.VISION, Modality.TEXT_AND_VISION):
                images = (
                    [(payload.image_bytes, payload.image_media_type)] if payload.image_bytes else []
                )
                for idx, (content, media_type) in enumerate(
                    [*images, *payload.additional_images], start=1
                ):
                    user_parts.append(f"Unit Image ({u.unit_id}, image {idx}):")
                    user_parts.append(BinaryContent(data=content, media_type=media_type))

        provider = self._build_provider()
        chat_model = OpenAIChatModel(model_id, provider=provider)
        agent = Agent(
            model=chat_model,
            output_type=StructuredDict(
                envelope_schema,
                name="extraction_envelope",
                description="Extracted field values and supporting unit evidence.",
            ),
            system_prompt=system_instructions,
            retries=self._max_retries,
            model_settings=ModelSettings(temperature=0.0),
        )

        async with self._semaphore:
            t0 = time.perf_counter()
            try:
                run_result = await agent.run(user_parts)
            except Exception as exc:
                raise ProviderError(
                    f"Extraction model '{model_id}' failed during '{stage_name}': {exc}"
                ) from exc
            latency_ms = int((time.perf_counter() - t0) * 1000)

        output_dict = run_result.output if isinstance(run_result.output, dict) else {}
        extracted_data, raw_evidences = _unpack_envelope_output(output_dict, target_fields)

        evidence_by_field: dict[str, list[Evidence]] = {f.path: [] for f in target_fields}
        name_to_path = {f.name: f.path for f in target_fields}

        for item in raw_evidences:
            if not isinstance(item, dict):
                continue
            raw_path = str(item.get("field_path") or "").strip()
            if not raw_path:
                continue
            if not raw_path.startswith("/"):
                raw_path = name_to_path.get(raw_path, f"/{raw_path}")
            matched_path = raw_path if raw_path in evidence_by_field else None
            if matched_path is None:
                top_seg = "/" + raw_path.lstrip("/").split("/")[0]
                if top_seg in evidence_by_field:
                    matched_path = top_seg
            if matched_path is None:
                continue
            uid = str(item.get("unit_id") or "").strip()
            quote = item.get("quote")
            evidence_by_field[matched_path].append(
                Evidence(
                    unit_id=uid,
                    locator={},
                    quote=str(quote) if quote is not None else None,
                )
            )

        raw_usage_attr = getattr(run_result, "usage", None)
        run_usage = raw_usage_attr() if callable(raw_usage_attr) else raw_usage_attr
        tokens_in = int(
            getattr(run_usage, "input_tokens", 0) or getattr(run_usage, "request_tokens", 0) or 0
        )
        tokens_out = int(
            getattr(run_usage, "output_tokens", 0) or getattr(run_usage, "response_tokens", 0) or 0
        )
        cost = estimate_cost_usd(model_id, tokens_in, tokens_out)

        usage_record = UsageRecord(
            usage_id=f"use_{uuid.uuid4().hex[:12]}",
            job_id=job_id,
            stage=stage_name,
            model_id=model_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost_usd=cost,
            latency_ms=latency_ms,
        )
        return ExtractionBatchResult(
            data=extracted_data,
            evidence_by_field=evidence_by_field,
            model_id=model_id,
            usage=usage_record,
        )
