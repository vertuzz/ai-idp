from __future__ import annotations

import asyncio
import base64
import json
import math
import time
import uuid
from typing import Any

import httpx

from ai_idp.adapters.outbound.openrouter.pricing import estimate_cost_usd
from ai_idp.application.ports.protocols import (
    ModalityResult,
    RelevanceResult,
    UnitInputPayload,
    VerificationBatchResult,
)
from ai_idp.domain.enums import DecisionKind, Modality, VerificationStatus
from ai_idp.domain.errors import (
    ModelInputLimitExceededError,
    PermanentProviderError,
    ProviderError,
    RateLimitedError,
)
from ai_idp.domain.models import (
    DecisionRecord,
    Evidence,
    ModalityDecision,
    TargetFieldSpec,
    UsageRecord,
    VerificationOutcome,
)


def _encode_data_url(image_bytes: bytes, media_type: str = "image/png") -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{media_type};base64,{b64}"


def _build_unit_state(
    payload: UnitInputPayload, extra_context: str = "", *, include_context: bool = True
) -> list[Any]:
    unit = payload.unit
    avail_names = [m.value for m in unit.available_modalities]
    header_lines = [
        f"Document Unit ID: {unit.unit_id} (kind={unit.kind.value}, ordinal={unit.ordinal})",
        f"Source Locator: {json.dumps(unit.source_locator, ensure_ascii=False)}",
        f"Available Modalities: {', '.join(avail_names) if avail_names else 'NONE'}",
        f"Unit Metadata: {json.dumps(unit.metadata, ensure_ascii=False)}",
    ]
    if extra_context:
        header_lines.append(extra_context)
    if payload.extraction_instructions:
        header_lines.append(f"Caller extraction instructions: {payload.extraction_instructions}")
    if include_context and payload.document_context:
        header_lines.append(f"Full document context:\n{payload.document_context}")
    if include_context and payload.prev_excerpt and not payload.document_context:
        header_lines.append(f"Preceding unit excerpt: {payload.prev_excerpt}")
    if include_context and payload.next_excerpt and not payload.document_context:
        header_lines.append(f"Following unit excerpt: {payload.next_excerpt}")
    if payload.native_text:
        header_lines.append(f"Extracted Native Text / Semantic Content:\n{payload.native_text}")
    else:
        header_lines.append("Extracted Native Text: <none available>")

    state: list[Any] = ["\n".join(header_lines)]
    images = [(payload.image_bytes, payload.image_media_type)] if payload.image_bytes else []
    for image_bytes, media_type in [*images, *payload.additional_images]:
        state.append(
            {
                "type": "image_url",
                "image_url": {"url": _encode_data_url(image_bytes, media_type)},
            }
        )
    return state


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError("Decision response has a non-numeric probability.")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ProviderError("Decision response probability is outside [0, 1].")
    return value


def _distribution(raw: Any, options: list[str]) -> dict[str, float]:
    if not isinstance(raw, dict) or set(raw) != set(options):
        raise ProviderError("Decision response has an incomplete probability distribution.")
    probabilities = {opt: _probability(raw[opt]) for opt in options}
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=0.01):
        raise ProviderError("Decision response probabilities do not sum to one.")
    return probabilities


def _parse_noul_answer(ans: Any) -> tuple[float, dict[str, float]]:
    if isinstance(ans, (int, float)):
        p_true = _probability(ans)
        return p_true, {"true": p_true, "false": round(max(0.0, 1.0 - p_true), 6)}
    if isinstance(ans, dict):
        if isinstance(ans.get("noul"), (int, float)):
            p_true = _probability(ans["noul"])
            return p_true, {"true": p_true, "false": round(max(0.0, 1.0 - p_true), 6)}
        probs = ans.get("probabilities") or ans.get("distribution") or ans
        if isinstance(probs, dict) and "true" in probs:
            distribution = _distribution(probs, ["true", "false"])
            return distribution["true"], distribution
    raise ProviderError("Decision response is missing a valid relevance answer.")


def _parse_choice_answer(ans: Any, options: list[str]) -> tuple[str, dict[str, float]]:
    if isinstance(ans, dict):
        probs_raw = ans.get("probabilities", ans.get("distribution"))
        probs = _distribution(probs_raw, options) if probs_raw is not None else {}
        chosen = ans.get("choice") or ans.get("selected")
        if isinstance(chosen, str) and chosen in options:
            if not probs:
                return chosen, {}
            if chosen != max(probs, key=probs.get):
                raise ProviderError("Decision choice conflicts with its probability distribution.")
            return chosen, probs
        if probs:
            best = max(probs.items(), key=lambda kv: kv[1])[0]
            return best, probs
    raise ProviderError("Decision response is missing a valid choice answer.")


class OpenRouterDecisionEngine:
    """Typed httpx adapter for the OpenRouter Decisions API (POST /api/alpha/decisions)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://openrouter.ai/api",
        max_concurrent_requests: int = 6,
        max_retries: int = 3,
        timeout_seconds: float = 60.0,
        semaphore: asyncio.Semaphore | None = None,
        limiter=None,
        max_input_bytes: int = 20 * 1024 * 1024,
        max_images: int = 8,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._timeout = timeout_seconds
        self._semaphore = semaphore or asyncio.Semaphore(max_concurrent_requests)
        self._limiter = limiter
        self._max_input_bytes = max_input_bytes
        self._max_images = max_images

    async def _post_decisions(
        self,
        model_id: str,
        state: list[Any],
        questions: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        if not self._api_key:
            raise ProviderError("OPENROUTER_API_KEY is not configured.")
        if (
            sum(isinstance(part, dict) and part.get("type") == "image_url" for part in state)
            > self._max_images
        ):
            raise ModelInputLimitExceededError("Decision request exceeds the model image limit.")

        url = f"{self._base_url}/alpha/decisions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ai-idp/0.1.0",
        }
        payload = {
            "model": model_id,
            "state": state,
            "questions": questions,
        }

        last_exc: Exception | None = None
        async with self._semaphore:
            for attempt in range(self._max_retries + 1):
                t0 = time.perf_counter()
                try:
                    from ai_idp.adapters.outbound.openrouter.transport import LimitedTransport

                    transport = (
                        LimitedTransport(self._limiter, self._max_input_bytes)
                        if self._limiter
                        else None
                    )
                    async with httpx.AsyncClient(
                        timeout=self._timeout, transport=transport
                    ) as client:
                        resp = await client.post(url, headers=headers, json=payload)
                    latency_ms = int((time.perf_counter() - t0) * 1000)

                    if resp.status_code == 429:
                        if attempt < self._max_retries:
                            await asyncio.sleep(1.0 * (2**attempt))
                            continue
                        raise RateLimitedError("OpenRouter Decisions API rate limit exceeded.")

                    if resp.status_code >= 500:
                        if attempt < self._max_retries:
                            await asyncio.sleep(0.8 * (2**attempt))
                            continue
                        raise ProviderError(
                            f"OpenRouter Decisions API server error ({resp.status_code})."
                        )

                    if resp.status_code >= 400:
                        raise PermanentProviderError(
                            f"OpenRouter Decisions API rejected the request ({resp.status_code})."
                        )

                    data = resp.json()
                    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
                        raise ProviderError("Malformed response from OpenRouter Decisions API.")
                    if any(key not in data["answers"] for key in questions):
                        raise ProviderError("OpenRouter Decisions API omitted a requested answer.")
                    return data, latency_ms
                except (httpx.RequestError, httpx.TimeoutException) as exc:
                    last_exc = exc
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.8 * (2**attempt))
                        continue
                    raise ProviderError("Network error calling OpenRouter Decisions API.") from exc

        raise ProviderError("Decision call failed after retries.") from last_exc

    def _build_usage_record(
        self,
        job_id: str,
        stage: str,
        requested_model: str,
        resp_data: dict[str, Any],
        latency_ms: int,
    ) -> UsageRecord:
        returned_model = str(resp_data.get("model") or requested_model)
        usage_raw = resp_data.get("usage") or {}
        tokens_in = int(usage_raw.get("prompt_tokens") or usage_raw.get("input_tokens") or 0)
        tokens_out = int(usage_raw.get("completion_tokens") or usage_raw.get("output_tokens") or 0)
        cost = estimate_cost_usd(returned_model, tokens_in, tokens_out, usage_raw)
        return UsageRecord(
            usage_id=f"use_{uuid.uuid4().hex[:12]}",
            job_id=job_id,
            stage=stage,
            model_id=returned_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            estimated_cost_usd=cost,
            latency_ms=latency_ms,
        )

    async def score_relevance(
        self,
        job_id: str,
        unit_payload: UnitInputPayload,
        fields: list[TargetFieldSpec],
        instructions: str,
        model_id: str,
        batch_questions: bool = True,
    ) -> RelevanceResult:
        extra = f"Extraction Instructions: {instructions}" if instructions else ""
        state = _build_unit_state(unit_payload, extra_context=extra)

        questions: dict[str, Any] = {}
        key_to_field: dict[str, TargetFieldSpec] = {}
        for idx, f in enumerate(fields):
            q_key = f"field_{idx}"
            key_to_field[q_key] = f
            desc = f" ({f.description})" if f.description else ""
            questions[q_key] = {
                "type": "noul",
                "instructions": (
                    f"Can this document unit directly provide or materially clarify the value "
                    f"of field '{f.name}'{desc}? Field schema: {json.dumps(f.raw_schema)}"
                ),
                "criteria": {
                    "false": f"This unit does not contain or clarify the value of '{f.name}'.",
                    "true": (
                        f"This unit directly states, tables, or visually shows "
                        f"the value of '{f.name}'."
                    ),
                },
            }

        field_scores: dict[str, float] = {}
        raw_distributions: dict[str, dict[str, float]] = {}
        records: list[DecisionRecord] = []

        if batch_questions:
            resp_data, latency_ms = await self._post_decisions(model_id, state, questions)
            returned_model = str(resp_data.get("model") or model_id)
            answers = resp_data.get("answers") or {}
            usage = self._build_usage_record(
                job_id, "scoring_relevance", model_id, resp_data, latency_ms
            )
            for q_key, f in key_to_field.items():
                p_true, dist = _parse_noul_answer(answers.get(q_key))
                field_scores[f.path] = p_true
                raw_distributions[f.path] = dist
                records.append(
                    DecisionRecord(
                        decision_id=f"dec_{uuid.uuid4().hex[:12]}",
                        job_id=job_id,
                        unit_id=unit_payload.unit.unit_id,
                        field_path=f.path,
                        kind=DecisionKind.RELEVANCE,
                        model_id=returned_model,
                        version="v1",
                        scores=dist,
                        selected=p_true >= 0.5,
                        latency_ms=latency_ms,
                        tokens_in=usage.tokens_in if q_key == "field_0" else 0,
                        tokens_out=usage.tokens_out if q_key == "field_0" else 0,
                        estimated_cost_usd=usage.estimated_cost_usd if q_key == "field_0" else 0.0,
                    )
                )
            return RelevanceResult(
                unit_id=unit_payload.unit.unit_id,
                field_scores=field_scores,
                raw_distributions=raw_distributions,
                decision_records=records,
                usage=usage,
            )

        # Unbatched fallback
        total_in = 0
        total_out = 0
        total_cost = 0.0
        total_lat = 0
        returned_model = model_id
        for q_key, f in key_to_field.items():
            resp_data, latency_ms = await self._post_decisions(
                model_id, state, {q_key: questions[q_key]}
            )
            returned_model = str(resp_data.get("model") or model_id)
            u = self._build_usage_record(
                job_id, "scoring_relevance", model_id, resp_data, latency_ms
            )
            total_in += u.tokens_in
            total_out += u.tokens_out
            total_cost += u.estimated_cost_usd
            total_lat += latency_ms
            p_true, dist = _parse_noul_answer((resp_data.get("answers") or {}).get(q_key))
            field_scores[f.path] = p_true
            raw_distributions[f.path] = dist
            records.append(
                DecisionRecord(
                    decision_id=f"dec_{uuid.uuid4().hex[:12]}",
                    job_id=job_id,
                    unit_id=unit_payload.unit.unit_id,
                    field_path=f.path,
                    kind=DecisionKind.RELEVANCE,
                    model_id=returned_model,
                    version="v1",
                    scores=dist,
                    selected=p_true >= 0.5,
                    latency_ms=latency_ms,
                    tokens_in=u.tokens_in,
                    tokens_out=u.tokens_out,
                    estimated_cost_usd=u.estimated_cost_usd,
                )
            )
        combined_usage = UsageRecord(
            usage_id=f"use_{uuid.uuid4().hex[:12]}",
            job_id=job_id,
            stage="scoring_relevance",
            model_id=returned_model,
            tokens_in=total_in,
            tokens_out=total_out,
            estimated_cost_usd=round(total_cost, 8),
            latency_ms=total_lat,
            call_count=len(key_to_field),
        )
        return RelevanceResult(
            unit_id=unit_payload.unit.unit_id,
            field_scores=field_scores,
            raw_distributions=raw_distributions,
            decision_records=records,
            usage=combined_usage,
        )

    async def select_modality(
        self,
        job_id: str,
        unit_payload: UnitInputPayload,
        fields: list[TargetFieldSpec],
        model_id: str,
    ) -> ModalityResult:
        field_summary = ", ".join(
            f"{f.name} ({f.description or f.field_type}; schema={json.dumps(f.raw_schema)})"
            for f in fields
        )
        state = _build_unit_state(
            unit_payload,
            extra_context=f"Target extraction fields: {field_summary}",
        )
        options = [Modality.TEXT.value, Modality.VISION.value, Modality.TEXT_AND_VISION.value]
        questions = {
            "modality": {
                "type": "choice",
                "instructions": (
                    "Which extraction modality should be used for this document unit to accurately "
                    "extract the target fields?"
                ),
                "criteria": {
                    "TEXT": (
                        "Extracted native text/HTML is complete, well-ordered, and "
                        "sufficient without viewing the image."
                    ),
                    "VISION": (
                        "Native text is missing, scanned, or unreliable; the rendered "
                        "page or embedded image is required."
                    ),
                    "TEXT_AND_VISION": (
                        "Both native text and the visual image are needed (e.g., complex "
                        "layout, embedded label image, or table verification)."
                    ),
                },
            }
        }
        resp_data, latency_ms = await self._post_decisions(model_id, state, questions)
        returned_model = str(resp_data.get("model") or model_id)
        usage = self._build_usage_record(
            job_id, "selecting_modality", model_id, resp_data, latency_ms
        )
        chosen_str, probs = _parse_choice_answer(
            (resp_data.get("answers") or {}).get("modality"), options
        )
        chosen_modality = Modality(chosen_str)
        available = unit_payload.unit.available_modalities
        limitation: str | None = None

        if chosen_modality not in available:
            limitation = (
                f"Requested modality {chosen_modality.value} is unavailable; "
                f"available={[m.value for m in available]}"
            )
            if Modality.TEXT_AND_VISION in available:
                chosen_modality = Modality.TEXT_AND_VISION
            elif Modality.VISION in available:
                chosen_modality = Modality.VISION
            else:
                chosen_modality = available[0] if available else Modality.TEXT

        decision = ModalityDecision(
            unit_id=unit_payload.unit.unit_id,
            modality=chosen_modality,
            raw_probabilities=probs,
            policy_version="v1",
            available_modalities=available,
            capability_limitation=limitation,
        )
        record = DecisionRecord(
            decision_id=f"dec_{uuid.uuid4().hex[:12]}",
            job_id=job_id,
            unit_id=unit_payload.unit.unit_id,
            field_path=None,
            kind=DecisionKind.MODALITY,
            model_id=returned_model,
            version="v1",
            scores=probs,
            selected={
                "modality": chosen_modality.value,
                "requested": chosen_str,
                "available": [m.value for m in available],
                "capability_limitation": limitation,
            }
            if limitation
            else chosen_modality.value,
            latency_ms=latency_ms,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            estimated_cost_usd=usage.estimated_cost_usd,
        )
        return ModalityResult(decision=decision, decision_record=record, usage=usage)

    async def verify_fields(
        self,
        job_id: str,
        fields_to_verify: list[tuple[TargetFieldSpec, Any, list[Evidence]]],
        unit_payloads_by_id: dict[str, UnitInputPayload],
        model_id: str,
    ) -> VerificationBatchResult:
        if not fields_to_verify:
            return VerificationBatchResult()

        # Verification and absence checks need the complete original source, not only citations.
        referenced_ids = list(unit_payloads_by_id)

        state: list[Any] = []
        for uid in referenced_ids:
            p = unit_payloads_by_id[uid]
            state.extend(_build_unit_state(p, include_context=False))

        options = [
            VerificationStatus.SUPPORTED.value,
            VerificationStatus.CONTRADICTED.value,
            VerificationStatus.INSUFFICIENT_EVIDENCE.value,
        ]
        questions: dict[str, Any] = {}
        key_to_field: dict[str, tuple[TargetFieldSpec, Any]] = {}
        partial_scope = any(
            p.verification_scope != "complete_document" for p in unit_payloads_by_id.values()
        )
        for idx, (f_spec, val, evidences) in enumerate(fields_to_verify):
            q_key = f"verify_{idx}"
            key_to_field[q_key] = (f_spec, val)
            val_repr = json.dumps(val, ensure_ascii=False)
            quotes = [ev.quote for ev in evidences if ev.quote]
            quote_hint = (
                f" Cited quote(s): {json.dumps(quotes, ensure_ascii=False)}." if quotes else ""
            )
            desc_hint = f" Field description: {f_spec.description}." if f_spec.description else ""
            citations = json.dumps([ev.model_dump(mode="json") for ev in evidences])
            questions[q_key] = {
                "type": "choice",
                "instructions": (
                    (
                        "This is one bounded batch of a larger document. Inspect only this batch; "
                        "ignore citations to units outside it. For a populated value, absence from "
                        "this batch is INSUFFICIENT_EVIDENCE, not CONTRADICTED. A populated value "
                        "is SUPPORTED only if the batch supports the entire value and its local "
                        "citations. For null/empty values, SUPPORTED means absence in this batch; "
                        "the application requires absence in every batch. "
                        if partial_scope
                        else ""
                    )
                    + f"Verify whether the source document unit(s) support the extracted value "
                    f"for field '{f_spec.name}' = {val_repr}.{desc_hint}{quote_hint} "
                    f"Field schema: {json.dumps(f_spec.raw_schema)}. Citations: {citations}. "
                    "Check the entire value, including every array item and object property. "
                    "Honor the field schema and caller instructions, including any requirement "
                    "to preserve exact printed string formatting, punctuation, and units. "
                    "Source units can declare unavailable_images: their content was not rendered. "
                    "Do not treat unavailable visual content as evidence of absence. "
                    "For null or an empty collection, SUPPORTED means the complete document "
                    "establishes absence; if the answer is present return CONTRADICTED, "
                    "and if absence cannot be established return INSUFFICIENT_EVIDENCE. "
                    "For populated values, confirm that each cited unit and quote really "
                    "supports this field; support elsewhere does not repair an incorrect citation."
                ),
                "criteria": {
                    "SUPPORTED": (
                        "The source document text or image directly supports the extracted "
                        "value and its semantic meaning."
                    ),
                    "CONTRADICTED": (
                        "The source document conflicts with or contradicts the extracted "
                        "value (e.g. wrong number, superseded draft, or fabricated value)."
                    ),
                    "INSUFFICIENT_EVIDENCE": (
                        "The source document is missing the value, illegible, or too "
                        "ambiguous to confirm."
                    ),
                },
            }

        resp_data, latency_ms = await self._post_decisions(model_id, state, questions)
        returned_model = str(resp_data.get("model") or model_id)
        usage = self._build_usage_record(job_id, "verifying", model_id, resp_data, latency_ms)
        answers = resp_data.get("answers") or {}

        outcomes: dict[str, VerificationOutcome] = {}
        records: list[DecisionRecord] = []
        primary_unit_id = referenced_ids[0] if referenced_ids else None

        for q_key, (f_spec, _val) in key_to_field.items():
            chosen_str, probs = _parse_choice_answer(answers.get(q_key), options)
            status = VerificationStatus(chosen_str)
            outcomes[f_spec.path] = VerificationOutcome(
                field_path=f_spec.path,
                status=status,
                raw_probabilities=probs,
                model_id=returned_model,
            )
            records.append(
                DecisionRecord(
                    decision_id=f"dec_{uuid.uuid4().hex[:12]}",
                    job_id=job_id,
                    unit_id=primary_unit_id,
                    field_path=f_spec.path,
                    kind=DecisionKind.VERIFICATION,
                    model_id=returned_model,
                    version="v1",
                    scores=probs,
                    selected=status.value,
                    latency_ms=latency_ms,
                    tokens_in=usage.tokens_in if q_key == "verify_0" else 0,
                    tokens_out=usage.tokens_out if q_key == "verify_0" else 0,
                    estimated_cost_usd=usage.estimated_cost_usd if q_key == "verify_0" else 0.0,
                )
            )

        return VerificationBatchResult(
            outcomes=outcomes,
            decision_records=records,
            usage=usage,
        )
