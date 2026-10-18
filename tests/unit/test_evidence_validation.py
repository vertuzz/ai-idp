from __future__ import annotations

from ai_idp.application.services.pipeline import ExtractionPipelineService
from ai_idp.domain.enums import (
    CheckOutcome,
    FieldStatus,
    Modality,
    UnitKind,
    VerificationStatus,
)
from ai_idp.domain.models import (
    CheckResult,
    DocumentUnit,
    Evidence,
    FieldValue,
    PipelineConfiguration,
    TargetFieldSpec,
    TextSpan,
    VerificationOutcome,
)
from ai_idp.domain.validation import (
    extract_qualifiers,
    extract_units_and_currency,
    is_ambiguous_date_notation,
    is_ambiguous_numeric_notation,
    validate_field_association,
    validate_source_anchoring,
    validate_typed_value,
)


def _make_unit(
    unit_id: str, kind: UnitKind = UnitKind.PDF_PAGE, modalities: list[Modality] | None = None
) -> DocumentUnit:
    return DocumentUnit(
        unit_id=unit_id,
        document_id="doc_test",
        ordinal=1,
        kind=kind,
        native_text_ref="text_ref" if modalities and Modality.TEXT in modalities else None,
        image_ref="img_ref" if modalities and Modality.VISION in modalities else None,
    )


def test_1_mismatch_detected_when_text_differs():
    """1. Source has 55,834, candidate has 55,854: detect literal/typed mismatch."""
    unit = _make_unit("page_1", modalities=[Modality.TEXT])
    native_text = "Subtotal: 55,834 IDR\nTotal: 58,000 IDR"
    ev = Evidence(unit_id="page_1", quote="55,834")

    spec = TargetFieldSpec(path="/subtotal", name="subtotal", field_type="number")

    # Text anchoring matches source text
    anchor_res = validate_source_anchoring(
        unit=unit, native_text=native_text, evidence=ev, raw_or_quote="55,834"
    )
    assert anchor_res.outcome == CheckOutcome.PASS

    # Candidate extracted value 55854 does not match raw text 55,834
    typed_res = validate_typed_value(value=55854, raw_text="55,834", field_spec=spec)
    fail_res = [r for r in typed_res if r.outcome == CheckOutcome.FAIL]
    assert len(fail_res) == 1
    assert fail_res[0].reason_code == "NUMERIC_VALUE_MISMATCH"


def test_2_requested_number_on_another_page_fails():
    """2. Requested number exists on another page or only in prompt:
    do not treat as match to cited source.
    """
    unit_p1 = _make_unit("page_1", modalities=[Modality.TEXT])
    native_text_p1 = "Introduction and overview of the report."
    # Candidate cites page_1, but the number only existed on page_2
    ev = Evidence(unit_id="page_1", quote="960")

    res = validate_source_anchoring(
        unit=unit_p1, native_text=native_text_p1, evidence=ev, raw_or_quote="960"
    )
    assert res.outcome == CheckOutcome.FAIL
    assert res.reason_code == "TEXT_NOT_FOUND"


def test_3_token_inside_larger_number_no_match():
    """3. 100 occurs only inside 1000: no numeric-token match."""
    unit = _make_unit("page_1", modalities=[Modality.TEXT])
    native_text = "The measured frequency was 1000 kHz in all test samples."
    ev = Evidence(unit_id="page_1", quote="100")

    res = validate_source_anchoring(
        unit=unit, native_text=native_text, evidence=ev, raw_or_quote="100"
    )
    assert res.outcome == CheckOutcome.FAIL
    assert res.reason_code == "TEXT_NOT_FOUND"


def test_4_period_requires_semantic_check():
    """4. Both prior/current-year totals occur in source:
    text existence alone cannot bypass semantic check.
    """
    unit = _make_unit("page_1", modalities=[Modality.TEXT])
    native_text = "Fiscal 2021 Total: £500,000. Fiscal 2022 Total: £650,000."
    ev = Evidence(unit_id="page_1", quote="£500,000")

    # Mechanical check passes for text presence
    anchor_res = validate_source_anchoring(
        unit=unit, native_text=native_text, evidence=ev, raw_or_quote="£500,000"
    )
    assert anchor_res.outcome == CheckOutcome.PASS

    # But if semantic verifier flags CONTRADICTED (because field requested 2022 total, not 2021)
    fv = FieldValue(
        path="/total_2022",
        value=500000,
        status=FieldStatus.UNVERIFIED,
        sources=[ev],
        check_results=[anchor_res],
    )
    outcome = VerificationOutcome(
        field_path="/total_2022",
        status=VerificationStatus.CONTRADICTED,
        rationale="Source 500,000 is for fiscal 2021, not requested 2022.",
        model_id="test_model",
    )
    config = PipelineConfiguration()
    ExtractionPipelineService._apply_verification(fv, outcome, config)
    assert fv.verification == VerificationStatus.CONTRADICTED
    assert fv.status != FieldStatus.VERIFIED


def test_5_item_name_contains_copied_quantity_price():
    """5. Item name contains copied quantity/price; quantity missing: association failure."""
    assoc_res = validate_field_association(
        field_name="item_name",
        field_value="RTD Kunyit 1 15000",
    )
    fails = [r for r in assoc_res if r.outcome == CheckOutcome.FAIL]
    assert len(fails) == 1
    assert fails[0].reason_code == "MERGED_ITEM_FIELDS"


def test_6_table_values_association_and_completeness():
    """6. Table values: test parent/child association and completeness."""
    # When quantity is None for a required field
    spec_qty = TargetFieldSpec(
        path="/items/0/quantity", name="quantity", field_type="integer", nullable=False
    )
    qty_checks = validate_typed_value(value=None, raw_text=None, field_spec=spec_qty)
    assert any(
        c.outcome == CheckOutcome.FAIL and c.reason_code == "MISSING_REQUIRED_VALUE"
        for c in qty_checks
    )


def test_7_declared_normalized_amount_and_currency():
    """7. 1 200,00 EUR vs declared normalized amount: permit declared conversion."""
    raw = "1 200,00 EUR"
    curr = extract_units_and_currency(raw)
    assert curr == "EUR"

    spec = TargetFieldSpec(path="/amount", name="amount", field_type="number")
    typed_res = validate_typed_value(value=1200.00, raw_text=raw, field_spec=spec)
    exact_res = [r for r in typed_res if r.reason_code == "NUMERIC_VALUE_EXACT"]
    assert len(exact_res) == 1
    assert exact_res[0].outcome == CheckOutcome.PASS


def test_8_qualifier_preservation_around_number():
    """8. around 1.9 million vs 1.9 million: distinguish numeric agreement, approximation."""
    raw = "around 1.9 million"
    quals = extract_qualifiers(raw)
    assert "approximate" in quals

    spec = TargetFieldSpec(path="/households", name="households", field_type="number")
    typed_res = validate_typed_value(value=1900000, raw_text=raw, field_spec=spec)
    assert any(r.reason_code == "NUMERIC_VALUE_EXACT" for r in typed_res)


def test_9_identifier_integrity_leading_zeros_and_units():
    """9. Identifier 00123, negative amount, units: preserve their meaning; no blanket stripping."""
    spec_id = TargetFieldSpec(path="/employee_id", name="employee_id", field_type="string")
    # If candidate stripped leading zeros -> 123
    checks_loss = validate_typed_value(value="123", raw_text="00123", field_spec=spec_id)
    assert any(
        c.outcome == CheckOutcome.FAIL and c.reason_code == "LEADING_ZEROS_LOST"
        for c in checks_loss
    )

    # If candidate preserved leading zeros -> 00123
    checks_ok = validate_typed_value(value="00123", raw_text="00123", field_spec=spec_id)
    assert not any(c.outcome == CheckOutcome.FAIL for c in checks_ok)


def test_10_ambiguous_numeric_and_date_notation():
    """10. Ambiguous numeric/date notation: report uncertainty unless contract resolves it."""
    assert is_ambiguous_numeric_notation("1,234") is True
    assert is_ambiguous_numeric_notation("1,234.56") is False
    assert is_ambiguous_date_notation("03/04/2026") is True
    assert is_ambiguous_date_notation("25/04/2026") is False  # 25 can only be day


def test_11_repeated_quote_out_of_range_offsets_wrong_hash():
    """11. Repeated quote, out-of-range offsets, wrong source hash or unknown unit: reject."""
    unit = _make_unit("page_1", modalities=[Modality.TEXT])
    text = "Fee: £50. Total Fee: £50."

    # Repeated quote without offsets -> AMBIGUOUS_MULTIPLE_MATCHES
    ev_repeat = Evidence(unit_id="page_1", quote="£50")
    res_repeat = validate_source_anchoring(
        unit=unit, native_text=text, evidence=ev_repeat, raw_or_quote="£50"
    )
    assert res_repeat.outcome == CheckOutcome.INDETERMINATE
    assert res_repeat.reason_code == "AMBIGUOUS_MULTIPLE_MATCHES"

    # Out of range offsets -> SPAN_OUT_OF_BOUNDS
    ev_oor = Evidence(unit_id="page_1", text_span=TextSpan(start=0, end=999, text="out"))
    res_oor = validate_source_anchoring(
        unit=unit, native_text=text, evidence=ev_oor, raw_or_quote="out"
    )
    assert res_oor.outcome == CheckOutcome.FAIL
    assert res_oor.reason_code == "SPAN_OUT_OF_BOUNDS"

    # Wrong hash -> SOURCE_HASH_MISMATCH
    ev_hash = Evidence(
        unit_id="page_1", text_span=TextSpan(start=0, end=5, artifact_sha256="wrong_hash")
    )
    res_hash = validate_source_anchoring(
        unit=unit,
        native_text=text,
        evidence=ev_hash,
        raw_or_quote="Fee: ",
        expected_artifact_sha256="expected_hash",
    )
    assert res_hash.outcome == CheckOutcome.FAIL
    assert res_hash.reason_code == "SOURCE_HASH_MISMATCH"

    # Unknown unit -> UNKNOWN_UNIT
    res_unknown = validate_source_anchoring(
        unit=None, native_text=None, evidence=Evidence(unit_id="nonexistent")
    )
    assert res_unknown.outcome == CheckOutcome.FAIL
    assert res_unknown.reason_code == "UNKNOWN_UNIT"


def test_12_scan_or_docx_image_without_native_text():
    """12. Scan or DOCX embedded image without native text: text matching is NOT_APPLICABLE."""
    unit_scan = _make_unit("frame_1", kind=UnitKind.IMAGE_FRAME, modalities=[Modality.VISION])
    ev = Evidence(unit_id="frame_1", quote="Scanned Total 45.00")
    res = validate_source_anchoring(
        unit=unit_scan, native_text=None, evidence=ev, raw_or_quote="Scanned Total 45.00"
    )
    assert res.outcome == CheckOutcome.NOT_APPLICABLE
    assert res.reason_code == "NO_NATIVE_TEXT"


def test_13_text_and_image_conflict_recorded():
    """13. PDF text contradicts rendered image: keep conflict in diagnostics."""
    # When text anchoring fails, mechanical check records the failure
    unit = _make_unit("page_1", modalities=[Modality.TEXT, Modality.VISION])
    text = "Contract Price: £10,000"  # hidden stale layer says 10,000, image says 20,000
    ev = Evidence(unit_id="page_1", quote="£20,000")
    res = validate_source_anchoring(
        unit=unit, native_text=text, evidence=ev, raw_or_quote="£20,000"
    )
    assert res.outcome == CheckOutcome.FAIL


def test_14_derived_total_transformation_check():
    """14. Derived total is not literally printed: check declared transformation."""
    spec_derived = TargetFieldSpec(
        path="/calculated_sum",
        name="calculated_sum",
        field_type="number",
        description="Calculated sum of items",
    )
    # Value is Decimal sum, raw_text is None for derived field
    checks = validate_typed_value(value=150.0, raw_text=None, field_spec=spec_derived)
    # Does not falsely fail with string mismatch
    assert not any(c.outcome == CheckOutcome.FAIL for c in checks)


def test_15_missing_optional_field_coverage():
    """15. Missing optional field or empty array: no unsupported absence claim."""
    spec_opt = TargetFieldSpec(
        path="/optional_tax", name="optional_tax", field_type="number", nullable=True
    )
    checks = validate_typed_value(value=None, raw_text=None, field_spec=spec_opt)
    assert len(checks) == 1
    assert checks[0].outcome == CheckOutcome.NOT_APPLICABLE
    assert checks[0].reason_code == "NULL_OPTIONAL_VALUE"


def test_16_model_approval_cannot_override_mechanical_failure():
    """16. Model approves a mechanically inconsistent value: no silent promotion to verified."""
    ev = Evidence(unit_id="page_1", quote="55,854")
    failed_check = CheckResult(
        check_name="numeric_precision",
        outcome=CheckOutcome.FAIL,
        reason_code="NUMERIC_VALUE_MISMATCH",
        message="Candidate number differs from source.",
    )
    fv = FieldValue(
        path="/total",
        value=55854,
        status=FieldStatus.UNVERIFIED,
        sources=[ev],
        check_results=[failed_check],
    )

    # Verifier model returned SUPPORTED
    outcome = VerificationOutcome(
        field_path="/total",
        status=VerificationStatus.SUPPORTED,
        raw_probabilities={"SUPPORTED": 0.95, "CONTRADICTED": 0.05},
        model_id="test_model",
    )
    config = PipelineConfiguration(verification_supported_threshold=0.50)
    ExtractionPipelineService._apply_verification(fv, outcome, config)

    # Must be demoted to INSUFFICIENT_EVIDENCE because mechanical check failed
    assert fv.verification == VerificationStatus.INSUFFICIENT_EVIDENCE
    assert "Mechanical check failed" in (fv.unresolved_reason or "")
