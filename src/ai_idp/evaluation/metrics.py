from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ai_idp.domain.enums import VerificationStatus
from ai_idp.domain.field_paths import get_pointer
from ai_idp.domain.models import Evidence, ExtractionResult


def resolve_json_pointer(data: Any, pointer: str) -> tuple[bool, Any]:
    """Resolve a JSON Pointer (e.g. '/items/0/name') against extracted data."""
    return get_pointer(data, pointer)


def normalize_scalar(val: Any) -> Any:
    if isinstance(val, list):
        return [normalize_scalar(item) for item in val]
    if isinstance(val, dict):
        return {key: normalize_scalar(item) for key, item in val.items()}
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


def classify_field_comparison(
    extracted: Any,
    expected: Any,
) -> tuple[bool, bool, bool, str]:
    """Classify comparison between extracted and expected values.

    Returns (exact_match, normalized_match, semantic_match, category).
    Categories:
    - 'exact_match'
    - 'representation_only_difference'
    - 'incomplete_or_extra_content'
    - 'wrong_value'
    - 'omission'
    - 'unknown'
    """
    exact, norm = values_match(extracted, expected)
    if exact:
        return True, True, True, "exact_match"
    if extracted is None:
        return False, False, False, "omission"
    if expected is None:
        return False, False, False, "extra_field"
    if norm:
        return False, True, True, "representation_only_difference"

    if isinstance(extracted, str) and isinstance(expected, str):
        # Check unicode punctuation equivalence (curly quotes, dashes, non-breaking hyphens)
        def clean_punct(s: str) -> str:
            s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
            s = s.replace("‐", "-").replace("–", "-").replace("—", "-")
            s = re.sub(r"[.,]$", "", s.strip())
            return " ".join(s.split()).lower()

        c_ext = clean_punct(extracted)
        c_exp = clean_punct(expected)
        if c_ext == c_exp:
            return False, False, True, "representation_only_difference"

        # Check prefix/suffix differences (e.g. 'Volume 3' vs '3')
        # Numbers must NEVER be matched via prefix/suffix substrings (e.g. '1000' vs '100')
        is_num_ext = bool(re.fullmatch(r"[-+]?\d+(?:[.,]\d+)*", c_ext))
        is_num_exp = bool(re.fullmatch(r"[-+]?\d+(?:[.,]\d+)*", c_exp))
        if is_num_ext and is_num_exp:
            return False, False, False, "wrong_value"

        # Differences must respect word boundaries, and must NOT match antonyms/negations
        # e.g. 'inactive' vs 'active', 'not active' vs 'active'
        words_ext = c_ext.split()
        words_exp = c_exp.split()

        negation_words = {
            "not",
            "no",
            "non",
            "never",
            "without",
            "inactive",
            "unactive",
            "disabled",
            "off",
            "on",
            "active",
            "false",
            "true",
        }
        neg_ext = set(words_ext).intersection(negation_words)
        neg_exp = set(words_exp).intersection(negation_words)
        if neg_ext != neg_exp:
            return False, False, False, "wrong_value"

        # Check if one is a sub-phrase of the other with only boilerplate/label difference
        if len(words_ext) > len(words_exp):
            longer, shorter = words_ext, words_exp
        else:
            longer, shorter = words_exp, words_ext

        shorter_len = len(shorter)
        if shorter_len > 0:
            is_prefix = longer[:shorter_len] == shorter
            is_suffix = longer[-shorter_len:] == shorter
            if is_prefix or is_suffix:
                extra_words = set(longer[shorter_len:] if is_prefix else longer[:-shorter_len])
                boilerplate = {
                    "volume",
                    "vol",
                    "invoice",
                    "inv",
                    "total",
                    "page",
                    "pg",
                    "no",
                    "num",
                    "number",
                    "item",
                    "usd",
                    "eur",
                    "gbp",
                    "rub",
                    "$",
                    "€",
                    "£",
                    "qty",
                    "amount",
                    "subtotal",
                    "date",
                    "id",
                    "ref",
                    "#",
                }
                if extra_words.issubset(boilerplate):
                    return False, False, True, "incomplete_or_extra_content"
                return False, False, False, "incomplete_or_extra_content"

    return False, False, False, "wrong_value"


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
    semantic_match: bool = False
    comparison_category: str | None = None


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
    semantic_matches: int = 0
    representation_differences: int = 0
    substantive_mismatches: int = 0
    llm_calls: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    preparation_ms: int = 0
    failure_reason: str | None = None
    evidence_units_expected: int = 0
    evidence_units_selected: int = 0
    selected_units: int = 0
    units_total: int = 0
    recovered_fields: int = 0
    escalated_fields: int = 0
    missing_expected: int = 0
    missing_correct: int = 0
    verification_confusion: dict[str, int] = field(default_factory=dict)
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

        found, extracted_val = resolve_json_pointer(result.data, path)
        fv = result.fields.get(path)
        if not found and fv is not None and fv.value is None:
            found = True  # Explicit internal absence can omit an optional non-null property.
        exact_ok, norm_ok = values_match(extracted_val, expected_val)
        exact_ok, norm_ok = exact_ok and found, norm_ok and found
        _, _, sem_ok, comp_cat = classify_field_comparison(extracted_val, expected_val)
        sem_ok = sem_ok and found

        ext_sources = fv.sources if fv else []
        ver_status = fv.verification.value if (fv and fv.verification) else None

        ev_ok = evidence_matches(ext_sources, expected_sources)
        false_sup = (ver_status == VerificationStatus.SUPPORTED.value) and not norm_ok
        confusion_key = f"{ver_status or 'UNVERIFIED'}:{'correct' if norm_ok else 'incorrect'}"
        summary.verification_confusion[confusion_key] = (
            summary.verification_confusion.get(confusion_key, 0) + 1
        )
        if expected_val is None:
            summary.missing_expected += 1
            summary.missing_correct += int(found and extracted_val is None)
        if fv and len(fv.attempts) > 1:
            summary.escalated_fields += 1
            _, initially_correct = values_match(fv.attempts[0].value, expected_val)
            summary.recovered_fields += int(norm_ok and not initially_correct)

        summary.fields_total += 1
        if exact_ok:
            summary.exact_matches += 1
        if norm_ok:
            summary.normalized_matches += 1
        if sem_ok:
            summary.semantic_matches += 1
        if ev_ok:
            summary.evidence_matches += 1
        if false_sup:
            summary.false_supported_count += 1
        if comp_cat == "representation_only_difference" or (
            comp_cat == "incomplete_or_extra_content" and sem_ok
        ):
            summary.representation_differences += 1
        elif comp_cat in ("wrong_value", "omission", "extra_field") or (
            comp_cat == "incomplete_or_extra_content" and not sem_ok
        ):
            summary.substantive_mismatches += 1

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
                semantic_match=sem_ok,
                comparison_category=comp_cat,
            )
        )

    return summary
