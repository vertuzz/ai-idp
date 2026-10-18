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
    # Exactly 3 digits after a single comma or dot, e.g. '1,234' or '1.234'
    if re.search(r"(?:^|[^\d.,])[-+]?\d+[.,]\d{3}(?:[^\d.,]|$)", cleaned):
        return True
    return False


def is_unsupported_numeric_notation(text: str) -> bool:
    """Detect unsupported or non-standard numeric notations (fractions, hex, exponents, etc.)."""
    cleaned = text.strip()
    if re.search(r"\b\d+/\d+\b", cleaned):
        return True
    if re.search(r"\b0[xXbB][0-9a-fA-F]+\b", cleaned):
        return True
    if re.search(r"\d+\s*[\^|\*\*]\s*\d+", cleaned):
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


def _build_token_pattern(target: str) -> str:
    """Build regex pattern matching whole tokens, preserving signs and decimal fractions."""
    if re.fullmatch(r"[-+]?\d+(?:[.,\s]\d+)*", target):
        # Preceding boundary: cannot be preceded by digits, decimal/thousand separators, or sign
        pre_boundary = r"(?<![\d.,+-])"
        # Succeeding boundary:
        # If target has decimal fraction (e.g. '100.50'), cannot be followed by another digit
        # If target has no decimal fraction (e.g. '100'),
        # cannot be followed by digits or decimal point+digit
        if re.search(r"[.,]\d+$", target):
            post_boundary = r"(?!\d)"
        else:
            post_boundary = r"(?!(?:[.,]\d|\d))"
        return pre_boundary + re.escape(target) + post_boundary
    return r"(?<!\w)" + re.escape(target) + r"(?!\w)"


build_token_pattern = _build_token_pattern


def _check_span_token_boundaries(native_text: str, start: int, end: int, token: str) -> bool:
    """Verify that a span in native_text adheres to token boundaries for numbers or words."""
    is_numeric = bool(re.fullmatch(r"[-+]?\d+(?:[.,\s]\d+)*", token))
    if is_numeric:
        # Preceding boundary: cannot be preceded by digits, decimal/thousand separators, or sign
        if start > 0:
            char_before = native_text[start - 1]
            if char_before in "0123456789.,+-":
                return False
        # Succeeding boundary
        if end < len(native_text):
            after = native_text[end:]
            if re.search(r"[.,]\d+$", token):
                if after and after[0].isdigit():
                    return False
            else:
                if re.match(r"^(?:[.,]\d|\d)", after):
                    return False
        return True
    else:
        # General word boundary: cannot be preceded or succeeded by word characters
        if start > 0:
            char_before = native_text[start - 1]
            if char_before.isalnum() or char_before == "_":
                return False
        if end < len(native_text):
            char_after = native_text[end]
            if char_after.isalnum() or char_after == "_":
                return False
        return True


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
            if sliced != target_text and _normalize_whitespace(sliced) != _normalize_whitespace(
                target_text
            ):
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

        clean_target = (target_text or sliced).strip()
        if not _check_span_token_boundaries(native_text, span.start, span.end, clean_target):
            return CheckResult(
                check_name="source_anchoring",
                outcome=CheckOutcome.FAIL,
                reason_code="SPAN_BOUNDARY_VIOLATION",
                message=(
                    f"Text span [{span.start}:{span.end}] '{sliced}' violates token boundaries "
                    f"in source unit text."
                ),
                policy_version=policy_version,
                evidence_references=[evidence.unit_id],
            )

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

    pattern = _build_token_pattern(clean_target)
    matches = list(re.finditer(pattern, native_text))
    if len(matches) == 0:
        norm_native = _normalize_whitespace(native_text)
        norm_target = _normalize_whitespace(clean_target)
        norm_pattern = _build_token_pattern(norm_target)
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


def _parse_candidate_numbers_from_text(raw_text: str) -> list[Decimal]:
    """Parse all numeric candidate values and magnitudes from a text string."""
    results: list[Decimal] = []
    # Match numbers with optional magnitude word (million, billion, thousand) or scientific notation
    pattern = (
        r"[-+]?\d+(?:\.\d+)?[eE][-+]?\d+"
        r"|[-+]?(?:\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
        r"(?:\s*(?:million|billion|thousand))?"
    )
    for m in re.finditer(pattern, raw_text, flags=re.IGNORECASE):
        token = m.group(0).strip()
        if not token:
            continue

        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?[eE][-+]?\d+", token):
            try:
                results.append(Decimal(token))
                continue
            except (InvalidOperation, ValueError):
                pass

        multiplier = Decimal("1")
        if re.search(r"\bmillion\b", token, re.IGNORECASE):
            multiplier = Decimal("1000000")
        elif re.search(r"\bbillion\b", token, re.IGNORECASE):
            multiplier = Decimal("1000000000")
        elif re.search(r"\bthousand\b", token, re.IGNORECASE):
            multiplier = Decimal("1000")

        num_str = re.sub(r"\b(million|thousand|billion)\b", "", token, flags=re.IGNORECASE).strip()
        num_str = num_str.replace(" ", "")

        # European format with decimals: e.g. '1.200,00' or '1200,00'
        if re.search(r"\d+\.\d{3},\d+", num_str) or re.search(r"^\d+,\d{1,2}$", num_str):
            clean_str = num_str.replace(".", "").replace(",", ".")
            try:
                results.append(Decimal(clean_str) * multiplier)
            except (InvalidOperation, ValueError):
                pass
            continue

        # Ambiguous single separator with 3 digits: e.g. '1.234' or '1,234'
        if re.fullmatch(r"[-+]?\d{1,3}[.,]\d{3}$", num_str):
            try:
                dec_val = Decimal(num_str.replace(",", ".")) * multiplier
                results.append(dec_val)
            except (InvalidOperation, ValueError):
                pass
            try:
                th_val = Decimal(num_str.replace(".", "").replace(",", "")) * multiplier
                results.append(th_val)
            except (InvalidOperation, ValueError):
                pass
            continue

        # Multiple European thousands: e.g. '1.234.567'
        if re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3}){2,}$", num_str):
            clean_str = num_str.replace(".", "")
            try:
                results.append(Decimal(clean_str) * multiplier)
            except (InvalidOperation, ValueError):
                pass
            continue

        # Standard US format (or plain integer / decimal)
        clean_str = num_str.replace(",", "")
        try:
            val = Decimal(clean_str) * multiplier
            results.append(val)
        except (InvalidOperation, ValueError):
            continue
    return results


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
        if raw_text is not None and str(raw_text).strip():
            candidate_numbers = _parse_candidate_numbers_from_text(str(raw_text))
            try:
                cand_dec = Decimal(str(value))
                if any(cand_dec == src_dec for src_dec in candidate_numbers):
                    results.append(
                        CheckResult(
                            check_name="numeric_precision",
                            outcome=CheckOutcome.PASS,
                            reason_code="NUMERIC_VALUE_EXACT",
                            message=f"Candidate number {cand_dec} matches source decimal.",
                            policy_version=policy_version,
                        )
                    )
                elif is_unsupported_numeric_notation(str(raw_text)):
                    results.append(
                        CheckResult(
                            check_name="numeric_precision",
                            outcome=CheckOutcome.INDETERMINATE,
                            reason_code="UNSUPPORTED_NUMERIC_FORMAT",
                            message=(
                                f"Number string '{raw_text}' has unsupported format; "
                                f"cannot mechanically verify candidate {cand_dec}."
                            ),
                            policy_version=policy_version,
                        )
                    )
                elif candidate_numbers:
                    results.append(
                        CheckResult(
                            check_name="numeric_precision",
                            outcome=CheckOutcome.FAIL,
                            reason_code="NUMERIC_VALUE_MISMATCH",
                            message=(
                                f"Candidate number {cand_dec} does not match any numbers "
                                f"in source text: {candidate_numbers}."
                            ),
                            policy_version=policy_version,
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            check_name="numeric_precision",
                            outcome=CheckOutcome.INDETERMINATE,
                            reason_code="NO_NUMERIC_CONTENT",
                            message=(
                                f"No numeric tokens could be parsed from source text '{raw_text}'."
                            ),
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

    if "name" in field_name.lower():
        # Check if field ends with multiple bare trailing numbers separated by whitespace
        # e.g. "RTD Kunyit 1 15000"
        m = re.search(r"\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)\s*$", field_value)
        if m:
            n1, n2 = m.group(1), m.group(2)
            is_proven = False
            if item_fields is not None:
                known_col_vals = {
                    str(v).replace(",", "").replace(".", "").strip()
                    for k, v in item_fields.items()
                    if v is not None and str(v).strip()
                }
                c1 = n1.replace(",", "").replace(".", "").strip()
                c2 = n2.replace(",", "").replace(".", "").strip()
                if (
                    c1 in known_col_vals
                    or c2 in known_col_vals
                    or item_fields.get("quantity") is None
                ):
                    is_proven = True

            if is_proven:
                results.append(
                    CheckResult(
                        check_name="field_association",
                        outcome=CheckOutcome.FAIL,
                        reason_code="MERGED_ITEM_FIELDS",
                        message=(
                            f"Item name '{field_value}' contains proven merged "
                            f"quantity ({n1}) and price ({n2}) columns."
                        ),
                        policy_version=policy_version,
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_name="field_association",
                        outcome=CheckOutcome.INDETERMINATE,
                        reason_code="SUSPECTED_MERGED_FIELDS",
                        message=(
                            f"Item name '{field_value}' ends with multiple trailing "
                            f"numbers ({n1}, {n2}); suspected merged table columns "
                            "pending verification."
                        ),
                        policy_version=policy_version,
                    )
                )

    return results
