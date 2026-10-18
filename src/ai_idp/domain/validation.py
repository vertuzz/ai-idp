from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from ai_idp.domain.enums import CheckOutcome, Modality, UnitKind
from ai_idp.domain.models import CheckResult, DocumentUnit, Evidence, TargetFieldSpec


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.strip().split())


def extract_qualifiers(text: str) -> list[str]:
    """Extract known approximation and bound qualifiers from text."""
    lower = text.lower()
    qualifiers: list[str] = []
    patterns = [
        (r"\b(around|approx\.?|approximately|about)\b", "approximate"),
        (r"\b(at least|minimum|min\.?|or more|or greater)\b", "lower_bound"),
        (r"\b(as high as|at most|maximum|max\.?|up to)\b", "upper_bound"),
        (r"\b(excluding\s+vat|ex\.?\s*vat)\b", "excluding_vat"),
        (r"\b(including\s+vat|inc\.?\s*vat)\b", "including_vat"),
    ]
    for pat, tag in patterns:
        if re.search(pat, lower):
            qualifiers.append(tag)
    return qualifiers


def extract_units_and_currency(text: str) -> str | None:
    """Extract known currency or unit symbols/words."""
    patterns = [
        (r"£|GBP", "GBP"),
        (r"€|EUR", "EUR"),
        (r"\$|USD", "USD"),
        (r"\bMHz\b", "MHz"),
        (r"\byears?\b", "years"),
        (r"\bdays?\b", "days"),
        (r"\bmonths?\b", "months"),
        (r"\bkg\b", "kg"),
    ]
    for pat, unit in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return unit
    return None


def is_ambiguous_numeric_notation(text: str) -> bool:
    """Detect if a number string could be ambiguously European vs US format (e.g. '1,234')."""
    cleaned = text.strip()
    # e.g., '1,234' has exactly 3 digits after a single comma and no decimal dot
    if re.fullmatch(r"^\d+,\d{3}$", cleaned):
        return True
    return False


def is_ambiguous_date_notation(text: str) -> bool:
    """Detect if a numeric date string could be DD/MM vs MM/DD (both parts <= 12)."""
    match = re.fullmatch(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", text.strip())
    if match:
        p1, p2 = int(match.group(1)), int(match.group(2))
        if 1 <= p1 <= 12 and 1 <= p2 <= 12 and p1 != p2:
            return True
    return False


def validate_source_anchoring(
    *,
    unit: DocumentUnit | None,
    native_text: str | None,
    evidence: Evidence,
    raw_or_quote: str | None = None,
    expected_artifact_sha256: str | None = None,
    policy_version: str = "v1",
) -> CheckResult:
    """Mechanically validate source citation and literal text anchoring."""
    # 1. Validate unit identity
    if unit is None:
        return CheckResult(
            check_name="source_anchoring",
            outcome=CheckOutcome.FAIL,
            reason_code="UNKNOWN_UNIT",
            message=f"Cited unit '{evidence.unit_id}' does not exist in document.",
            policy_version=policy_version,
            evidence_references=[evidence.unit_id],
        )

    # 2. Check native text availability
    if not native_text or not native_text.strip():
        # Scanned or image-only unit without native text
        if unit.kind == UnitKind.IMAGE_FRAME or Modality.VISION in unit.available_modalities:
            return CheckResult(
                check_name="source_anchoring",
                outcome=CheckOutcome.NOT_APPLICABLE,
                reason_code="NO_NATIVE_TEXT",
                message="Cited unit has no native text layer; visual verification required.",
                policy_version=policy_version,
                evidence_references=[evidence.unit_id],
            )
        return CheckResult(
            check_name="source_anchoring",
            outcome=CheckOutcome.FAIL,
            reason_code="EMPTY_NATIVE_TEXT",
            message="Cited unit text artifact is empty.",
            policy_version=policy_version,
            evidence_references=[evidence.unit_id],
        )

    target_text = raw_or_quote or evidence.quote

    # 3. Span offset validation if text_span is provided
    if evidence.text_span is not None:
        span = evidence.text_span
        if expected_artifact_sha256 and span.artifact_sha256:
            if span.artifact_sha256 != expected_artifact_sha256:
                return CheckResult(
                    check_name="source_anchoring",
                    outcome=CheckOutcome.FAIL,
                    reason_code="SOURCE_HASH_MISMATCH",
                    message="Text artifact SHA256 does not match expected hash.",
                    policy_version=policy_version,
                    evidence_references=[evidence.unit_id],
                )

        if span.start < 0 or span.end > len(native_text) or span.start > span.end:
            return CheckResult(
                check_name="source_anchoring",
                outcome=CheckOutcome.FAIL,
                reason_code="SPAN_OUT_OF_BOUNDS",
                message=(
                    f"Text span [{span.start}:{span.end}] is out of bounds "
                    f"for text length {len(native_text)}."
                ),
                policy_version=policy_version,
                evidence_references=[evidence.unit_id],
            )

        sliced = native_text[span.start : span.end]
        if target_text is not None:
            if sliced == target_text:
                return CheckResult(
                    check_name="source_anchoring",
                    outcome=CheckOutcome.PASS,
                    reason_code="SPAN_EXACT_MATCH",
                    message="Exact text slice matches cited value at specified span.",
                    policy_version=policy_version,
                    evidence_references=[evidence.unit_id],
                )
            if _normalize_whitespace(sliced) == _normalize_whitespace(target_text):
                return CheckResult(
                    check_name="source_anchoring",
                    outcome=CheckOutcome.PASS,
                    reason_code="SPAN_NORMALIZED_MATCH",
                    message="Normalized text slice matches cited value at specified span.",
                    policy_version=policy_version,
                    evidence_references=[evidence.unit_id],
                )
            return CheckResult(
                check_name="source_anchoring",
                outcome=CheckOutcome.FAIL,
                reason_code="SPAN_TEXT_MISMATCH",
                message=(
                    f"Text at span [{span.start}:{span.end}] '{sliced}' "
                    f"does not match expected '{target_text}'."
                ),
                policy_version=policy_version,
                evidence_references=[evidence.unit_id],
            )
        return CheckResult(
            check_name="source_anchoring",
            outcome=CheckOutcome.PASS,
            reason_code="SPAN_BOUNDS_VALID",
            message="Span offsets are valid within unit text.",
            policy_version=policy_version,
            evidence_references=[evidence.unit_id],
        )

    # 4. Without precise span offsets, search only the cited unit's native text
    if not target_text:
        return CheckResult(
            check_name="source_anchoring",
            outcome=CheckOutcome.INDETERMINATE,
            reason_code="NO_QUOTE_OR_TEXT",
            message="No quote or raw text provided to locate in source unit text.",
            policy_version=policy_version,
            evidence_references=[evidence.unit_id],
        )

    clean_target = target_text.strip()
    if not clean_target:
        return CheckResult(
            check_name="source_anchoring",
            outcome=CheckOutcome.INDETERMINATE,
            reason_code="EMPTY_SEARCH_TEXT",
            message="Search text is empty.",
            policy_version=policy_version,
            evidence_references=[evidence.unit_id],
        )

    # Whole-token pattern matching (100 inside 1000 must NOT match 100)
    if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)*", clean_target):
        pattern = r"(?<!\d)" + re.escape(clean_target) + r"(?!\d)"
    else:
        pattern = r"(?<!\w)" + re.escape(clean_target) + r"(?!\w)"

    matches = list(re.finditer(pattern, native_text))
    if len(matches) == 0:
        norm_native = _normalize_whitespace(native_text)
        norm_target = _normalize_whitespace(clean_target)
        if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)*", norm_target):
            norm_pattern = r"(?<!\d)" + re.escape(norm_target) + r"(?!\d)"
        else:
            norm_pattern = r"(?<!\w)" + re.escape(norm_target) + r"(?!\w)"
        norm_matches = list(re.finditer(norm_pattern, norm_native))
        if len(norm_matches) == 1:
            return CheckResult(
                check_name="source_anchoring",
                outcome=CheckOutcome.PASS,
                reason_code="NORMALIZED_TEXT_FOUND",
                message="Normalized text token found in cited source unit.",
                policy_version=policy_version,
                evidence_references=[evidence.unit_id],
            )
        if len(norm_matches) > 1:
            return CheckResult(
                check_name="source_anchoring",
                outcome=CheckOutcome.INDETERMINATE,
                reason_code="AMBIGUOUS_MULTIPLE_MATCHES",
                message=(
                    f"Text '{clean_target}' occurs {len(norm_matches)} times in cited unit "
                    "without precise span offsets."
                ),
                policy_version=policy_version,
                evidence_references=[evidence.unit_id],
            )
        return CheckResult(
            check_name="source_anchoring",
            outcome=CheckOutcome.FAIL,
            reason_code="TEXT_NOT_FOUND",
            message=f"Text token '{clean_target}' not found in cited unit native text.",
            policy_version=policy_version,
            evidence_references=[evidence.unit_id],
        )

    if len(matches) > 1:
        return CheckResult(
            check_name="source_anchoring",
            outcome=CheckOutcome.INDETERMINATE,
            reason_code="AMBIGUOUS_MULTIPLE_MATCHES",
            message=(
                f"Text '{clean_target}' occurs {len(matches)} times in cited unit "
                "without precise span offsets."
            ),
            policy_version=policy_version,
            evidence_references=[evidence.unit_id],
        )

    return CheckResult(
        check_name="source_anchoring",
        outcome=CheckOutcome.PASS,
        reason_code="EXACT_UNIQUE_TEXT_MATCH",
        message="Unique exact text token found in cited source text.",
        policy_version=policy_version,
        evidence_references=[evidence.unit_id],
    )


def validate_typed_value(
    *,
    value: Any,
    raw_text: str | None,
    field_spec: TargetFieldSpec,
    declared_format: str | None = None,
    policy_version: str = "v1",
) -> list[CheckResult]:
    """Conservative typed-value and representation checks."""
    results: list[CheckResult] = []

    # Null handling
    if value is None:
        if field_spec.nullable:
            results.append(
                CheckResult(
                    check_name="typed_value",
                    outcome=CheckOutcome.NOT_APPLICABLE,
                    reason_code="NULL_OPTIONAL_VALUE",
                    message="Field is null and optional.",
                    policy_version=policy_version,
                )
            )
        else:
            results.append(
                CheckResult(
                    check_name="typed_value",
                    outcome=CheckOutcome.FAIL,
                    reason_code="MISSING_REQUIRED_VALUE",
                    message="Field is non-nullable but has null value.",
                    policy_version=policy_version,
                )
            )
        return results

    if raw_text is None:
        results.append(
            CheckResult(
                check_name="typed_value",
                outcome=CheckOutcome.INDETERMINATE,
                reason_code="NO_RAW_TEXT",
                message="Cannot verify typed conversion without raw source text.",
                policy_version=policy_version,
            )
        )
        return results

    # 1. Identifier checks: preserve leading zeros, case, punctuation
    is_identifier = (
        "id" in field_spec.name.lower()
        or "code" in field_spec.name.lower()
        or "number" in field_spec.name.lower()
        or field_spec.raw_schema.get("format") in ("uri", "uuid", "regex")
    )
    if is_identifier and isinstance(raw_text, str) and re.match(r"^0+\d+$", raw_text.strip()):
        # Raw text has leading zeros, e.g. "00123"
        str_val = str(value)
        if str_val != raw_text.strip():
            results.append(
                CheckResult(
                    check_name="identifier_integrity",
                    outcome=CheckOutcome.FAIL,
                    reason_code="LEADING_ZEROS_LOST",
                    message=(
                        f"Identifier lost leading zero(s): raw '{raw_text}' vs extracted '{value}'."
                    ),
                    policy_version=policy_version,
                )
            )
            return results

    # 2. Ambiguity checks for numeric / date notation
    if isinstance(raw_text, str):
        if is_ambiguous_numeric_notation(raw_text) and not declared_format:
            results.append(
                CheckResult(
                    check_name="numeric_ambiguity",
                    outcome=CheckOutcome.INDETERMINATE,
                    reason_code="AMBIGUOUS_NUMERIC_NOTATION",
                    message=(
                        f"Number string '{raw_text}' has ambiguous separators "
                        "without declared format."
                    ),
                    policy_version=policy_version,
                )
            )
        if is_ambiguous_date_notation(raw_text) and not declared_format:
            results.append(
                CheckResult(
                    check_name="date_ambiguity",
                    outcome=CheckOutcome.INDETERMINATE,
                    reason_code="AMBIGUOUS_DATE_FORMAT",
                    message=(
                        f"Date '{raw_text}' has ambiguous day/month order without declared format."
                    ),
                    policy_version=policy_version,
                )
            )

    # 3. Numeric / Decimal checks
    if field_spec.field_type in ("integer", "number") or isinstance(value, (int, float, Decimal)):
        # Extract numeric magnitude if words like 'million' exist
        multiplier = Decimal("1")
        if re.search(r"\bmillion\b", str(raw_text), re.IGNORECASE):
            multiplier = Decimal("1000000")

        num_part = re.sub(r"\b(million|thousand|billion)\b", "", str(raw_text), flags=re.IGNORECASE)
        clean_num_str = re.sub(r"[^\d,.-]", "", num_part).strip()
        # If European format with dots for thousands and comma for decimal:
        # e.g., '1.200,00' or '1200,00'
        if re.search(r"\d+\.\d{3},\d+", clean_num_str) or re.search(r"^\d+,\d{2}$", clean_num_str):
            clean_num_str = clean_num_str.replace(".", "").replace(",", ".")
        else:
            clean_num_str = clean_num_str.replace(",", "")

        match = re.search(r"[-+]?\d+(?:\.\d+)?", clean_num_str)
        if match:
            try:
                raw_dec = Decimal(match.group(0)) * multiplier
                cand_dec = Decimal(str(value))
                if raw_dec != cand_dec:
                    # Do not allow fuzzy/edit-distance digit acceptance (e.g. 55854 vs 55834)
                    results.append(
                        CheckResult(
                            check_name="numeric_precision",
                            outcome=CheckOutcome.FAIL,
                            reason_code="NUMERIC_VALUE_MISMATCH",
                            message=(
                                f"Candidate number {cand_dec} does not equal "
                                f"source number {raw_dec}."
                            ),
                            policy_version=policy_version,
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            check_name="numeric_precision",
                            outcome=CheckOutcome.PASS,
                            reason_code="NUMERIC_VALUE_EXACT",
                            message=f"Candidate number {cand_dec} matches source decimal.",
                            policy_version=policy_version,
                        )
                    )
            except (InvalidOperation, ValueError):
                pass

    return results


def validate_field_association(
    *,
    field_name: str,
    field_value: Any,
    item_fields: dict[str, Any] | None = None,
    policy_version: str = "v1",
) -> list[CheckResult]:
    """Check parent/child and line-item field association integrity."""
    results: list[CheckResult] = []
    if not isinstance(field_value, str):
        return results

    # If field is an item name, check if it contains concatenated quantity/price tokens
    # e.g. "RTD Kunyit 1 15000" where price and quantity leaked into name
    if "name" in field_name.lower():
        trailing_numbers = re.findall(r"\b\d+(?:[.,]\d+)?\b", field_value)
        if len(trailing_numbers) >= 2:
            # Name has multiple numbers at the end (likely quantity + price merged)
            results.append(
                CheckResult(
                    check_name="field_association",
                    outcome=CheckOutcome.FAIL,
                    reason_code="MERGED_ITEM_FIELDS",
                    message=(
                        f"Item name '{field_value}' appears to contain merged "
                        "quantity and price numbers."
                    ),
                    policy_version=policy_version,
                )
            )

    return results
