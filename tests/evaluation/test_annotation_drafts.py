import pytest

from ai_idp.domain.enums import UnitKind
from ai_idp.domain.models import DocumentUnit
from scripts.draft_corpus_annotations import make_annotation


def test_model_draft_has_valid_schema_and_preserves_unreviewed_status():
    unit = DocumentUnit(
        unit_id="page_000001",
        document_id="source",
        ordinal=1,
        kind=UnitKind.PDF_PAGE,
        source_locator={"page_number": 1},
    )
    annotation = make_annotation(
        "case",
        [
            {
                "name": "document_title",
                "description": "Title",
                "value_json": '"Example"',
                "unit_ids": [unit.unit_id],
                "quote": "Example",
            }
        ],
        [unit],
    )
    assert annotation["review_status"] == "pending_human_review"
    assert annotation["schema"]["properties"]["document_title"]["type"] == "string"
    assert annotation["expected_fields"][0]["sources"][0]["locator"] == {"page_number": 1}
    with_non_scalar = make_annotation(
        "case",
        [
            {
                "name": "title",
                "description": "Title",
                "value_json": '"Example"',
                "unit_ids": [unit.unit_id],
                "quote": "Example",
            },
            {
                "name": "unsupported",
                "description": "List",
                "value_json": '["item"]',
                "unit_ids": [unit.unit_id],
                "quote": "item",
            },
        ],
        [unit],
    )
    assert len(with_non_scalar["expected_fields"]) == 1
    assert with_non_scalar["draft_warnings"]
    with pytest.raises(ValueError, match="unknown"):
        make_annotation(
            "case",
            [
                {
                    "name": "title",
                    "description": "Title",
                    "value_json": '"Example"',
                    "unit_ids": ["invented"],
                    "quote": "Example",
                }
            ],
            [unit],
        )
