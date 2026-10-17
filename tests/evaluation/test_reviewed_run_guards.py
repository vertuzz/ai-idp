import hashlib
import json
from unittest.mock import Mock

import pytest

from ai_idp.evaluation.runner import aggregate, load_manifest_cases, run_evaluation_suite
from scripts.review_corpus import record_ai_review, validate_annotation
from tests.integration.test_pipeline_recovery import SCHEMA, setup


def test_unreviewed_cases_are_not_benchmarks_and_draft_mode_cannot_cross_splits(tmp_path):
    path = tmp_path / "manifest.jsonl"
    path.write_text(
        json.dumps(
            {
                "case_id": "draft",
                "split": "development",
                "annotation_path": "draft.json",
                "evaluation_ready": False,
            }
        )
        + "\n",
        "utf-8",
    )
    assert load_manifest_cases(path) == []
    assert len(load_manifest_cases(path, allow_draft=True)) == 1
    with pytest.raises(ValueError):
        load_manifest_cases(path, case_ids=["draft"])
    with pytest.raises(ValueError):
        load_manifest_cases(path, allow_draft=True, split="holdout")


def test_empty_metrics_do_not_claim_perfect_accuracy():
    assert aggregate([])["normalized_accuracy"] is None


def test_ai_review_preserves_human_and_rights_gates_and_hashes_exact_bytes(tmp_path):
    corpus = tmp_path / "eval"
    corpus.mkdir()
    original = tmp_path / "source.txt"
    original.write_bytes(b"Project-owned sample")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    case = {
        "case_id": "sample",
        "path": "source.txt",
        "sha256": digest,
        "rights_status": "pending",
        "group_review": "pending",
        "evaluation_ready": False,
    }
    manifest = corpus / "manifest.jsonl"
    manifest.write_text(json.dumps(case) + "\n", "utf-8")
    draft = tmp_path / "review.json"
    annotation = {
        "case_id": "sample",
        "schema": SCHEMA,
        "expected_fields": [
            {
                "path": "/record_id",
                "value": "sample",
                "sources": [{"unit_id": "page_000001", "quote": "sample"}],
            }
        ],
        "review_status": "ai_reviewed",
        "reviewer_type": "ai",
        "reviewer_id": "codex",
        "review_notes": ["Source inspected"],
        "source_sha256": digest,
    }
    draft.write_text(json.dumps(annotation), "utf-8")
    record_ai_review(tmp_path, "sample", draft)
    recorded = json.loads(manifest.read_text("utf-8"))
    assert recorded["annotation_status"] == "ai_reviewed"
    assert recorded["evaluation_ready"] is False
    assert recorded["rights_status"] == recorded["group_review"] == "pending"
    target = tmp_path / recorded["annotation_path"]
    assert (
        recorded["ai_reviewed_annotation_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    )
    assert b"\r\n" not in target.read_bytes()
    original.write_bytes(b"Changed source")
    with pytest.raises(ValueError, match="changed"):
        record_ai_review(tmp_path, "sample", draft)


async def test_ai_reference_tampering_is_rejected_before_document_or_model_work(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"synthetic source")
    annotation = tmp_path / "ai.json"
    annotation.write_text(
        json.dumps(
            {
                "case_id": "sample",
                "review_status": "ai_reviewed",
                "reviewer_type": "ai",
            }
        ),
        "utf-8",
    )
    with pytest.raises(ValueError, match="fingerprint"):
        await run_evaluation_suite(
            Mock(),
            [
                {
                    "case_id": "sample",
                    "split": "development",
                    "annotation_status": "ai_reviewed",
                    "annotation_path": "ai.json",
                    "path": "source.pdf",
                    "sha256": "source-hash",
                    "ai_reviewed_annotation_sha256": "before-edit-hash",
                }
            ],
            root_dir=tmp_path,
            allow_draft=True,
        )


def test_restore_does_not_silently_replace_missing_ai_review_with_a_draft(tmp_path, monkeypatch):
    from scripts import prepare_corpus

    original = tmp_path / "source.pdf"
    original.write_bytes(b"synthetic source bytes")
    corpus = tmp_path / "eval"
    corpus.mkdir()
    case = {
        "case_id": "sample",
        "source": "gov_uk_pdf",
        "path": "source.pdf",
        "sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "annotation_status": "ai_reviewed",
        "annotation_path": "eval/missing.json",
    }
    (corpus / "manifest.jsonl").write_text(json.dumps(case) + "\n", "utf-8")
    monkeypatch.setattr(prepare_corpus, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match="reviewed answer set"):
        prepare_corpus.main()
    assert not (corpus / "missing.json").exists()


async def test_preparation_failure_remains_in_each_profile_denominator(tmp_path):
    container, _, _ = setup(tmp_path)
    container.ingest_use_case = Mock()
    container.ingest_use_case.execute.side_effect = ValueError("private decoder details")
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"invalid PDF")
    annotation = tmp_path / "draft.json"
    annotation.write_text(
        json.dumps(
            {
                "case_id": "bad",
                "schema": SCHEMA,
                "expected_fields": [{"path": "/record_id", "value": "expected"}],
            }
        ),
        "utf-8",
    )
    report = await run_evaluation_suite(
        container,
        [
            {
                "case_id": "bad",
                "split": "development",
                "path": "bad.pdf",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "annotation_path": "draft.json",
            }
        ],
        root_dir=tmp_path,
        allow_draft=True,
        profiles=["default", "always_vision"],
    )
    for metrics in report["summary_by_profile"].values():
        assert metrics["cases_count"] == metrics["failures"] == 1
        assert metrics["normalized_accuracy"] == 0
    assert all(c["failure_reason"] == "ValueError" for c in report["cases"])
    assert "private decoder details" not in json.dumps(report)


def test_review_cannot_approve_schema_inconsistent_answers():
    with pytest.raises(ValueError, match="schema"):
        validate_annotation(
            {
                "case_id": "one",
                "schema": {
                    "type": "object",
                    "properties": {"value": {"type": "number"}},
                    "required": ["value"],
                },
                "expected_fields": [
                    {"path": "/value", "value": "wrong", "sources": [{"unit_id": "one"}]}
                ],
            },
            "one",
        )
