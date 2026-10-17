from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ai_idp.domain.enums import VerificationStatus
from ai_idp.domain.models import Evidence, ExtractionResult


def resolve_json_pointer(data: Any, pointer: str) -> tuple[bool, Any]:
    """Resolve a JSON Pointer (e.g. '/items/0/name') against extracted data."""
    if not pointer or pointer == "/":
        return True, data
    parts = pointer.lstrip("/").split("/")
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                return False, None
            if idx < 0 or idx >= len(current):
                return False, None
            current = current[idx]
        else:
            return False, None
    return True, current


def normalize_scalar(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        collapsed = " ".join(val.strip().split())
        # Normalize receipt quantity format like "1 x" or "2x" -> 1.0 / 2.0
        qty_match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[xX]", collapsed)
        if qty_match:
            return float(qty_match.group(1))
        # Check if numeric-like string with thousand separators
        num_candidate = re.sub(r"[,_\s]", "", collapsed)
        if re.fullmatch(r"[-+]?\d+(\.\d+)?", num_candidate):
            try:
                return float(num_candidate)
            except ValueError:
                pass
        return collapsed.lower()
    return val


def values_match(extracted: Any, expected: Any) -> tuple[bool, bool]:
    """Return (exact_match, normalized_match)."""
    exact = extracted == expected
    if exact:
        return True, True
    if extracted is None or expected is None:
        return False, False
    norm_ext = normalize_scalar(extracted)
    norm_exp = normalize_scalar(expected)
    if isinstance(norm_ext, float) and isinstance(norm_exp, float):
        return False, abs(norm_ext - norm_exp) <= 1e-4
    if isinstance(extracted, str) and isinstance(expected, str):
        collapsed_ext = " ".join(extracted.strip().split()).lower()
        collapsed_exp = " ".join(expected.strip().split()).lower()
        if collapsed_ext == collapsed_exp:
            return False, True
    return False, norm_ext == norm_exp


def evidence_matches(
    extracted_sources: list[Evidence],
    expected_sources: list[dict[str, Any]],
) -> bool:
    """Check whether extracted evidence cites at least one expected source unit or locator."""
    if not expected_sources:
        return True
    if not extracted_sources:
        return False

    for exp in expected_sources:
        exp_uid = exp.get("unit_id")
        exp_loc = exp.get("locator") or {}
        for ext in extracted_sources:
            if exp_uid and ext.unit_id == exp_uid:
                return True
            if exp_loc:
                if (
                    "page_number" in exp_loc
                    and ext.locator.get("page_number") == exp_loc["page_number"]
                ):
                    return True
                if (
                    "frame_index" in exp_loc
                    and ext.locator.get("frame_index") == exp_loc["frame_index"]
                ):
                    return True
                if (
                    "embedded_image" in exp_loc
                    and ext.locator.get("embedded_image") == exp_loc["embedded_image"]
                ):
                    return True
                if "heading" in exp_loc and ext.locator.get("heading"):
                    if str(exp_loc["heading"]).lower() in str(ext.locator["heading"]).lower():
                        return True
    return False


@dataclass
class FieldScoreDetail:
    path: str
    expected: Any
    extracted: Any
    exact_match: bool
    normalized_match: bool
    evidence_match: bool
    verification: str | None = None
    false_supported: bool = False


@dataclass
class CaseEvaluationSummary:
    case_id: str
    source: str
    format: str
    split: str
    model_profile: str
    job_id: str
    status: str
    schema_valid: bool
    fields_total: int = 0
    exact_matches: int = 0
    normalized_matches: int = 0
    evidence_matches: int = 0
    false_supported_count: int = 0
    llm_calls: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    field_details: list[FieldScoreDetail] = field(default_factory=list)

    @property
    def exact_accuracy(self) -> float:
        return round(self.exact_matches / self.fields_total, 4) if self.fields_total else 0.0

    @property
    def normalized_accuracy(self) -> float:
        return round(self.normalized_matches / self.fields_total, 4) if self.fields_total else 0.0

    @property
    def evidence_recall(self) -> float:
        return round(self.evidence_matches / self.fields_total, 4) if self.fields_total else 0.0


def score_extraction_result(
    *,
    case_id: str,
    source: str,
    doc_format: str,
    split: str,
    model_profile: str,
    result: ExtractionResult,
    expected_fields: list[dict[str, Any]],
) -> CaseEvaluationSummary:
    summary = CaseEvaluationSummary(
        case_id=case_id,
        source=source,
        format=doc_format,
        split=split,
        model_profile=model_profile,
        job_id=result.job_id,
        status=result.status.value,
        schema_valid=result.schema_valid,
        llm_calls=result.usage.llm_calls,
        estimated_cost_usd=result.usage.estimated_cost_usd,
        latency_ms=result.usage.total_latency_ms,
    )

    for exp_item in expected_fields:
        path = str(exp_item.get("path") or "")
        expected_val = exp_item.get("value")
        expected_sources = exp_item.get("sources") or []

        _found, extracted_val = resolve_json_pointer(result.data, path)
        exact_ok, norm_ok = values_match(extracted_val, expected_val)

        top_path = "/" + path.lstrip("/").split("/")[0]
        fv = result.fields.get(path) or result.fields.get(top_path)
        ext_sources = fv.sources if fv else []
        ver_status = fv.verification.value if (fv and fv.verification) else None

        ev_ok = evidence_matches(ext_sources, expected_sources)
        false_sup = (ver_status == VerificationStatus.SUPPORTED.value) and not norm_ok

        summary.fields_total += 1
        if exact_ok:
            summary.exact_matches += 1
        if norm_ok:
            summary.normalized_matches += 1
        if ev_ok:
            summary.evidence_matches += 1
        if false_sup:
            summary.false_supported_count += 1

        summary.field_details.append(
            FieldScoreDetail(
                path=path,
                expected=expected_val,
                extracted=extracted_val,
                exact_match=exact_ok,
                normalized_match=norm_ok,
                evidence_match=ev_ok,
                verification=ver_status,
                false_supported=false_sup,
            )
        )

    return summary
