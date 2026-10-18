from typing import Any

from ai_idp.application.ports.protocols import UnitInputPayload
from ai_idp.application.services.pipeline import ExtractionPipelineService
from ai_idp.domain.enums import (
    CheckOutcome,
    FieldStatus,
    JobStatus,
    Modality,
    UnitKind,
    VerificationStatus,
)
from ai_idp.domain.models import (
    CheckResult,
    DocumentUnit,
    Evidence,
    ExtractionResult,
    ExtractionSpecification,
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
    # Proven structural violation when item_fields shows quantity missing/merged
    assoc_res = validate_field_association(
        field_name="item_name",
        field_value="RTD Kunyit 1 15000",
        item_fields={"quantity": None, "price": 15000},
    )
    fails = [r for r in assoc_res if r.outcome == CheckOutcome.FAIL]
    assert len(fails) == 1
    assert fails[0].reason_code == "MERGED_ITEM_FIELDS"

    # Without proven structure, it is a signal (INDETERMINATE), not a hard FAIL veto
    suspect_res = validate_field_association(
        field_name="item_name",
        field_value="RTD Kunyit 1 15000",
    )
    assert any(r.outcome == CheckOutcome.INDETERMINATE for r in suspect_res)
    assert not any(r.outcome == CheckOutcome.FAIL for r in suspect_res)

    # Legitimate product name with numbers and units is not failed
    ok_res = validate_field_association(
        field_name="item_name",
        field_value="iPhone 16 Pro 256 GB",
    )
    assert not any(r.outcome == CheckOutcome.FAIL for r in ok_res)


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


def test_17_coverage_recovery_runs_mechanical_checks_and_catches_fake_quote():
    """17. Recovery re-extraction cannot bypass mechanical checks with fabricated quote."""
    unit = _make_unit("page_1", modalities=[Modality.TEXT])
    fake_ev = Evidence(unit_id="page_1", quote="Nonexistent fabricated quote 9999")
    fv = FieldValue(
        path="/total",
        value=9999,
        status=FieldStatus.UNVERIFIED,
        sources=[fake_ev],
    )
    spec = TargetFieldSpec(path="/total", name="total", field_type="integer")
    payload = UnitInputPayload(unit=unit, native_text="Document has Total: 1,200 USD")

    ExtractionPipelineService._run_mechanical_checks(fv, spec, {"page_1": payload})
    fails = [c for c in fv.check_results if c.outcome == CheckOutcome.FAIL]
    assert len(fails) > 0
    assert any(c.reason_code == "TEXT_NOT_FOUND" for c in fails)

    # Verification must be gated by the failed check
    outcome = VerificationOutcome(
        field_path="/total",
        status=VerificationStatus.SUPPORTED,
        raw_probabilities={"SUPPORTED": 0.99},
        model_id="test",
    )
    config = PipelineConfiguration()
    ExtractionPipelineService._apply_verification(fv, outcome, config)
    assert fv.verification == VerificationStatus.INSUFFICIENT_EVIDENCE


def test_18_quote_containing_multiple_numbers_matches_candidate_value():
    """18. Multi-number quotes (e.g. 'Total for 2025: 1,200') do not smash digits together."""
    spec = TargetFieldSpec(path="/total", name="total", field_type="integer")
    # Candidate value 1200 in "Total for 2025: 1,200" must succeed
    checks = validate_typed_value(value=1200, raw_text="Total for 2025: 1,200", field_spec=spec)
    assert any(
        c.outcome == CheckOutcome.PASS and c.reason_code == "NUMERIC_VALUE_EXACT" for c in checks
    )
    assert not any(c.outcome == CheckOutcome.FAIL for c in checks)

    # Candidate value 2025 also matches if extracting year
    checks_yr = validate_typed_value(value=2025, raw_text="Total for 2025: 1,200", field_spec=spec)
    assert any(c.outcome == CheckOutcome.PASS for c in checks_yr)

    # But candidate 1300 fails against "Total for 2025: 1,200"
    checks_mismatch = validate_typed_value(
        value=1300, raw_text="Total for 2025: 1,200", field_spec=spec
    )
    assert any(
        c.outcome == CheckOutcome.FAIL and c.reason_code == "NUMERIC_VALUE_MISMATCH"
        for c in checks_mismatch
    )


def test_19_product_name_with_numbers_and_units_not_vetoed():
    """19. Legitimate names with numbers like 'iPhone 16 Pro 256 GB' do not get hard FAIL."""
    results = validate_field_association(
        field_name="product_name",
        field_value="iPhone 16 Pro 256 GB",
    )
    assert not any(r.outcome == CheckOutcome.FAIL for r in results)


def test_20_numeric_token_boundary_prevents_loss_of_sign_and_fraction():
    """20. Source search for 100 must not match -100 or 100.50."""
    unit = _make_unit("page_1", modalities=[Modality.TEXT])
    ev_100 = Evidence(unit_id="page_1", quote="100")

    # Native text has -100: searching 100 must fail
    res_neg = validate_source_anchoring(
        unit=unit,
        native_text="Balance is -100 USD",
        evidence=ev_100,
        raw_or_quote="100",
    )
    assert res_neg.outcome == CheckOutcome.FAIL

    # Native text has 100.50: searching 100 must fail
    res_frac = validate_source_anchoring(
        unit=unit,
        native_text="Balance is 100.50 USD",
        evidence=ev_100,
        raw_or_quote="100",
    )
    assert res_frac.outcome == CheckOutcome.FAIL

    # Searching exact -100 in -100 USD must pass
    ev_neg = Evidence(unit_id="page_1", quote="-100")
    res_ok_neg = validate_source_anchoring(
        unit=unit,
        native_text="Balance is -100 USD",
        evidence=ev_neg,
        raw_or_quote="-100",
    )
    assert res_ok_neg.outcome == CheckOutcome.PASS

    # Searching exact 100.50 in 100.50 USD must pass
    ev_frac = Evidence(unit_id="page_1", quote="100.50")
    res_ok_frac = validate_source_anchoring(
        unit=unit,
        native_text="Balance is 100.50 USD",
        evidence=ev_frac,
        raw_or_quote="100.50",
    )
    assert res_ok_frac.outcome == CheckOutcome.PASS


def test_21_metrics_classification_avoids_false_semantic_match():
    """21. classify_field_comparison rejects numbers (1000 vs 100)
    and antonyms (inactive vs active)."""
    from ai_idp.evaluation.metrics import classify_field_comparison

    # 1000 vs 100: must be wrong_value, NOT semantic match
    _, _, sem_num, cat_num = classify_field_comparison(extracted="1000", expected="100")
    assert sem_num is False
    assert cat_num == "wrong_value"

    # inactive vs active: must be wrong_value, NOT semantic match
    _, _, sem_ant, cat_ant = classify_field_comparison(extracted="inactive", expected="active")
    assert sem_ant is False
    assert cat_ant == "wrong_value"

    # Volume 3 vs 3: genuine boilerplate label difference is semantic match
    _, _, sem_vol, cat_vol = classify_field_comparison(extracted="Volume 3", expected="3")
    assert sem_vol is True
    assert cat_vol == "incomplete_or_extra_content"


def test_22_normalize_evidences_anchors_text_span_and_hash():
    """22. _normalize_evidences preserves text_span and computes SHA256 when unique quote exists."""
    unit = _make_unit("page_1", modalities=[Modality.TEXT])
    payload = UnitInputPayload(unit=unit, native_text="Sample header\nInvoice # 12345\nFooter text")
    ev = Evidence(unit_id="page_1", quote="Invoice # 12345")

    norm_evs = ExtractionPipelineService._normalize_evidences(
        [ev],
        unit_by_id={"page_1": unit},
        default_unit_ids=["page_1"],
        payload_by_id={"page_1": payload},
    )
    assert len(norm_evs) == 1
    assert norm_evs[0].text_span is not None
    assert norm_evs[0].text_span.start == 14
    assert norm_evs[0].text_span.end == 29
    assert norm_evs[0].text_span.text == "Invoice # 12345"
    assert norm_evs[0].text_span.artifact_sha256 is not None


async def test_23_escalation_targets_cited_problematic_units_on_first_attempt():
    """23. Escalation starts with the problematic cited page rather than entire document."""
    from ai_idp.application.ports.protocols import ExtractionBatchResult
    from ai_idp.domain.models import ExtractionRun

    extracted_units_passed: list[list[str]] = []

    class MockExtractor:
        async def extract_fields(self, **kwargs):
            unit_inputs = kwargs.get("unit_inputs", [])
            extracted_units_passed.append([p.unit.unit_id for p, _ in unit_inputs])
            return ExtractionBatchResult(
                data={"total": 1200},
                evidence_by_field={"/total": [Evidence(unit_id="page_3", quote="Total: 1,200")]},
                model_id="escalation_model",
            )

    class MockDecisionEngine:
        async def verify_fields(self, **kwargs):
            from ai_idp.application.ports.protocols import VerificationBatchResult

            return VerificationBatchResult(
                outcomes={
                    "/total": VerificationOutcome(
                        field_path="/total",
                        status=VerificationStatus.SUPPORTED,
                        model_id="dec_model",
                    )
                }
            )

    class FakeJobRepo:
        def get_job(self, *args, **kwargs):
            return job

        def is_cancelled(self, *args, **kwargs):
            return False

    class FakeResultRepo:
        def load_step(self, *args, **kwargs):
            return None

        def save_step(self, *args, **kwargs):
            pass

        def record_field_attempt(self, *args, **kwargs):
            pass

        def record_decisions(self, *args, **kwargs):
            pass

    class MockTelemetry:
        def span(self, *args, **kwargs):
            from contextlib import nullcontext

            return nullcontext()

    service = ExtractionPipelineService(
        blob_store=None,
        document_reader=None,
        relevance_engine=None,
        extraction_engine=MockExtractor(),
        decision_engine=MockDecisionEngine(),
        job_repo=FakeJobRepo(),
        result_repo=FakeResultRepo(),
        telemetry=MockTelemetry(),
    )

    u1 = _make_unit("page_1", modalities=[Modality.TEXT, Modality.TEXT_AND_VISION])
    u2 = _make_unit("page_2", modalities=[Modality.TEXT, Modality.TEXT_AND_VISION])
    u3 = _make_unit("page_3", modalities=[Modality.TEXT, Modality.TEXT_AND_VISION])

    payloads = {
        "page_1": UnitInputPayload(unit=u1, native_text="Page 1 text"),
        "page_2": UnitInputPayload(unit=u2, native_text="Page 2 text"),
        "page_3": UnitInputPayload(unit=u3, native_text="Page 3 text Total: 1,200"),
    }

    # Field failed on page 3
    ev = Evidence(unit_id="page_3", quote="Total: 1,200")
    fv = FieldValue(
        path="/total",
        value=1100,
        status=FieldStatus.UNVERIFIED,
        verification=VerificationStatus.INSUFFICIENT_EVIDENCE,
        sources=[ev],
    )
    spec_field = TargetFieldSpec(path="/total", name="total", field_type="integer")
    run_spec = ExtractionSpecification(
        spec_id="spec_1", schema_hash="hash1", schema_json={}, fields=[spec_field]
    )
    job = ExtractionRun(
        job_id="test_esc",
        document_id="doc_test",
        spec_id="spec_1",
        configuration=PipelineConfiguration(max_field_extra_attempts=1),
    )

    await service._run_escalation(
        job=job,
        spec=run_spec,
        fields_to_escalate=[spec_field],
        field_values={"/total": fv},
        payload_by_id=payloads,
        unit_by_id={"page_1": u1, "page_2": u2, "page_3": u3},
        record_usage=lambda u: None,
    )

    # First attempt must target page_3 ONLY, not all 3 pages
    assert len(extracted_units_passed) == 1
    assert extracted_units_passed[0] == ["page_3"]


def test_24_token_boundary_in_span_normalization_and_verification():
    """24. [P1] Auto-anchoring and coordinate validation checks number boundaries."""
    u1 = _make_unit("page_1", modalities=[Modality.TEXT])
    payload_1000 = UnitInputPayload(unit=u1, native_text="Total: 1000 USD")
    payload_neg = UnitInputPayload(unit=u1, native_text="Balance: -100 USD")
    payload_frac = UnitInputPayload(unit=u1, native_text="Price: 100.50 USD")

    ev_100 = Evidence(unit_id="page_1", quote="100")

    # 1. Normalization must NOT auto-generate coordinates pointing inside 1000, -100, or 100.50
    for p in (payload_1000, payload_neg, payload_frac):
        norm = ExtractionPipelineService._normalize_evidences(
            [ev_100],
            unit_by_id={"page_1": u1},
            default_unit_ids=["page_1"],
            payload_by_id={"page_1": p},
        )
        assert len(norm) == 1
        assert norm[0].text_span is None

    # 2. When coordinates point inside 1000, validation must FAIL with SPAN_BOUNDARY_VIOLATION
    span_inside_1000 = TextSpan(start=7, end=10, text="100")
    ev_with_span = Evidence(unit_id="page_1", quote="100", text_span=span_inside_1000)
    res_1000 = validate_source_anchoring(
        unit=u1,
        native_text="Total: 1000 USD",
        evidence=ev_with_span,
        raw_or_quote="100",
    )
    assert res_1000.outcome == CheckOutcome.FAIL
    assert res_1000.reason_code == "SPAN_BOUNDARY_VIOLATION"

    # Coordinates pointing inside -100 must also fail
    span_inside_neg = TextSpan(start=10, end=13, text="100")
    ev_with_neg_span = Evidence(unit_id="page_1", quote="100", text_span=span_inside_neg)
    res_neg = validate_source_anchoring(
        unit=u1,
        native_text="Balance: -100 USD",
        evidence=ev_with_neg_span,
        raw_or_quote="100",
    )
    assert res_neg.outcome == CheckOutcome.FAIL
    assert res_neg.reason_code == "SPAN_BOUNDARY_VIOLATION"


def test_25_multiple_sources_different_pages_and_quotes_full_path():
    """25. [P1] Two legitimate citations (e.g. '1,200' on page 1 and '1200' on page 2)
    both pass source anchoring in full pipeline mechanical check."""
    u1 = _make_unit("page_1", modalities=[Modality.TEXT])
    u2 = _make_unit("page_2", modalities=[Modality.TEXT])

    payloads = {
        "page_1": UnitInputPayload(unit=u1, native_text="Summary Total: 1,200 USD"),
        "page_2": UnitInputPayload(unit=u2, native_text="Itemized Subtotal: 1200 USD"),
    }

    ev1 = Evidence(unit_id="page_1", quote="1,200", raw_value="1,200")
    ev2 = Evidence(unit_id="page_2", quote="1200", raw_value="1200")

    fv = FieldValue(
        path="/total",
        value=1200,
        raw_value="1,200",
        status=FieldStatus.UNVERIFIED,
        sources=[ev1, ev2],
    )
    spec_field = TargetFieldSpec(path="/total", name="total", field_type="integer")

    ExtractionPipelineService._run_mechanical_checks(fv, spec_field, payloads)

    anchor_checks = [c for c in fv.check_results if c.check_name == "source_anchoring"]
    assert len(anchor_checks) == 2
    assert all(c.outcome == CheckOutcome.PASS for c in anchor_checks)


def test_26_ambiguous_and_scientific_number_handling():
    """26. [P1] Ambiguous numbers (1.234) and scientific notation (1e3) accept valid formats,
    and unsupported notations (3/4) return INDETERMINATE without hard FAIL."""
    spec_num = TargetFieldSpec(path="/val", name="val", field_type="number")
    spec_int = TargetFieldSpec(path="/val", name="val", field_type="integer")

    # 1. Decimal 1.234 matches candidate Decimal('1.234')
    res_dec = validate_typed_value(value=1.234, raw_text="1.234", field_spec=spec_num)
    assert any(
        c.outcome == CheckOutcome.PASS and c.reason_code == "NUMERIC_VALUE_EXACT" for c in res_dec
    )
    assert not any(c.outcome == CheckOutcome.FAIL for c in res_dec)

    # 2. Decimal 1.234 under European thousands matches candidate 1234
    res_th = validate_typed_value(value=1234, raw_text="1.234", field_spec=spec_int)
    assert any(
        c.outcome == CheckOutcome.PASS and c.reason_code == "NUMERIC_VALUE_EXACT" for c in res_th
    )
    assert not any(c.outcome == CheckOutcome.FAIL for c in res_th)

    # 3. Scientific notation 1e3 matches candidate 1000
    res_sci = validate_typed_value(value=1000, raw_text="1e3", field_spec=spec_int)
    assert any(
        c.outcome == CheckOutcome.PASS and c.reason_code == "NUMERIC_VALUE_EXACT" for c in res_sci
    )
    assert not any(c.outcome == CheckOutcome.FAIL for c in res_sci)

    # 4. Unsupported format like fraction 3/4 returns INDETERMINATE, not hard FAIL
    res_frac = validate_typed_value(value=0.75, raw_text="3/4", field_spec=spec_num)
    assert any(
        c.outcome == CheckOutcome.INDETERMINATE and c.reason_code == "UNSUPPORTED_NUMERIC_FORMAT"
        for c in res_frac
    )
    assert not any(c.outcome == CheckOutcome.FAIL for c in res_frac)


def test_27_qualifiers_and_units_reset_between_attempts():
    """27. [P2] Qualifiers and unit are freshly recomputed per attempt;
    replacing 'around $100' with 'EUR 90' clears approximate and USD."""
    u1 = _make_unit("page_1", modalities=[Modality.TEXT])
    payloads = {
        "page_1": UnitInputPayload(
            unit=u1, native_text="Price was around $100 but adjusted to EUR 90"
        ),
    }
    spec_field = TargetFieldSpec(path="/price", name="price", field_type="number")

    # Attempt 1: 'around $100'
    ev1 = Evidence(unit_id="page_1", quote="around $100")
    fv = FieldValue(
        path="/price",
        value=100,
        raw_value="around $100",
        status=FieldStatus.UNVERIFIED,
        sources=[ev1],
    )
    ExtractionPipelineService._run_mechanical_checks(fv, spec_field, payloads)
    assert "approximate" in fv.qualifiers
    assert fv.unit == "USD"

    # Attempt 2: corrected to 'EUR 90'
    ev2 = Evidence(unit_id="page_1", quote="EUR 90")
    fv.value = 90
    fv.raw_value = "EUR 90"
    fv.sources = [ev2]
    ExtractionPipelineService._run_mechanical_checks(fv, spec_field, payloads)
    assert fv.qualifiers == []
    assert fv.unit == "EUR"


def test_28_metrics_incomplete_extra_content_substantive_mismatch():
    """28. [P2] Incomplete or extra content with non-boilerplate words (missing year or name)
    is counted under substantive_mismatches, not representation_differences."""
    from ai_idp.evaluation.metrics import score_extraction_result

    def make_res(data_dict: dict[str, Any]) -> ExtractionResult:
        field_vals = {
            f"/{k}": FieldValue(
                path=f"/{k}",
                value=v,
                status=FieldStatus.VERIFIED,
                verification=VerificationStatus.SUPPORTED,
            )
            for k, v in data_dict.items()
        }
        return ExtractionResult(
            job_id="job_1",
            document_id="doc_1",
            spec_id="spec_1",
            status=JobStatus.COMPLETED,
            schema_valid=True,
            data=data_dict,
            fields=field_vals,
        )

    # Case A: Missing year ("Report" extracted vs "Report 2024" expected)
    res_a = make_res({"title": "Report"})
    summary_a = score_extraction_result(
        case_id="case_a",
        source="test",
        doc_format="pdf",
        split="test",
        model_profile="test",
        result=res_a,
        expected_fields=[{"path": "/title", "value": "Report 2024"}],
    )
    assert summary_a.substantive_mismatches == 1
    assert summary_a.representation_differences == 0

    # Case B: Missing model name ("iPhone 16" extracted vs "iPhone 16 Pro" expected)
    res_b = make_res({"title": "iPhone 16"})
    summary_b = score_extraction_result(
        case_id="case_b",
        source="test",
        doc_format="pdf",
        split="test",
        model_profile="test",
        result=res_b,
        expected_fields=[{"path": "/title", "value": "iPhone 16 Pro"}],
    )
    assert summary_b.substantive_mismatches == 1
    assert summary_b.representation_differences == 0

    # Case C: Genuine boilerplate difference ("3" vs "Volume 3") remains representation difference
    res_c = make_res({"title": "3"})
    summary_c = score_extraction_result(
        case_id="case_c",
        source="test",
        doc_format="pdf",
        split="test",
        model_profile="test",
        result=res_c,
        expected_fields=[{"path": "/title", "value": "Volume 3"}],
    )
    assert summary_c.representation_differences == 1
    assert summary_c.substantive_mismatches == 0
