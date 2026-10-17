import json

import pytest

pytest.importorskip("pypdf")
pytest.importorskip("docx")
Image = pytest.importorskip("PIL.Image")

# The corpus validator uses the optional evaluation dependency group.
from scripts import validate_corpus as corpus  # noqa: E402
from scripts.prepare_cord_preview import sha256  # noqa: E402


@pytest.fixture
def small_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "QUOTAS", {"fixture": 2})
    monkeypatch.setattr(corpus, "SPLITS", {"development": 1, "holdout": 1})
    cases = []
    for index, (color, split) in enumerate([("white", "development"), ("black", "holdout")]):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (16, 16), color).save(path)
        annotation_path = tmp_path / f"{index}.json"
        annotation_path.write_text(
            json.dumps(
                {
                    "case_id": str(index),
                    "review_status": "pending_human_review",
                    "expected_fields": [],
                }
            ),
            encoding="utf-8",
        )
        cases.append(
            {
                "case_id": str(index),
                "source": "fixture",
                "split": split,
                "group_id": str(index),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "path": path.name,
                "format": "png",
                "license_url": "https://example.invalid",
                "attribution": "Original fixture",
                "annotation_path": annotation_path.name,
                "annotation_status": "not_annotated",
                "evaluation_ready": False,
            }
        )
    return tmp_path, cases


def test_file_coverage_is_separate_from_benchmark_readiness(small_corpus):
    root, cases = small_corpus
    report = corpus.validate(cases, root)
    assert report["file_integrity_passed"]
    assert report["evaluation_ready"] == 0


def test_tampered_file_is_rejected(small_corpus):
    root, cases = small_corpus
    (root / cases[0]["path"]).write_bytes(b"changed")
    assert any("SHA-256 mismatch" in error for error in corpus.validate(cases, root)["errors"])


def test_group_leakage_and_false_review_claim_are_rejected(small_corpus):
    root, cases = small_corpus
    cases[1]["group_id"] = cases[0]["group_id"]
    cases[0]["evaluation_ready"] = True
    errors = corpus.validate(cases, root)["errors"]
    assert any("crosses splits" in error for error in errors)
    assert any("Unreviewed annotation" in error for error in errors)


def test_corpus_path_cannot_escape_repository(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        corpus.safe_path(tmp_path, "../outside.png")
