from ai_idp.application.services.record_evidence import anchor_value


def test_record_anchoring_uses_exact_original_text_and_decimal_equivalence():
    text = "Header 2.50\nLOT-01 Amount 2.50\nLOT-02 Amount 3.75"
    evidence = anchor_value(2.5, text, text.index("LOT-01"), text.index("LOT-02"), "unit")
    assert evidence.quote == "2.50"
    assert text[evidence.text_span.start : evidence.text_span.end] == evidence.quote
    assert evidence.locator["anchor_method"] == "unique_value_in_model_cited_record"


def test_ambiguous_or_outside_record_matches_never_create_evidence():
    assert anchor_value(2, "Qty 2 Price 2", 0, 13, "unit") is None
    assert anchor_value(10, "Header 10\nRecord 11", 10, 19, "unit") is None
    assert anchor_value(40, "A40: LOT-01", 0, 11, "unit") is None
