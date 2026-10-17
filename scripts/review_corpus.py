"""Prepare annotation review packs; record explicit human or AI source reviews separately."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_idp.domain.field_paths import get_pointer, set_pointer
from ai_idp.domain.schema_normalizer import (
    normalize_extraction_schema,
    validate_data_against_schema,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_manifest(path: Path, cases: list[dict[str, Any]]) -> None:
    data = ("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".manifest-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_annotation(annotation: dict[str, Any], case_id: str) -> None:
    if annotation.get("case_id") != case_id:
        raise ValueError("Annotation identity does not match the selected source.")
    normalize_extraction_schema(annotation.get("schema", {}))
    fields = annotation.get("expected_fields", [])
    if not fields:
        raise ValueError("A reviewed annotation must contain expected field values.")
    data: dict[str, Any] = {}
    seen = set()
    for field in sorted(fields, key=lambda f: len(f["path"].split("/"))):
        pointer = field["path"]
        if pointer in seen:
            raise ValueError("Duplicate expected field path.")
        seen.add(pointer)
        set_pointer(data, pointer, field["value"])
        if field["value"] not in (None, [], {}) and not field.get("sources"):
            raise ValueError("Populated reference values require source evidence.")
    valid, errors = validate_data_against_schema(data, annotation["schema"])
    if not valid:
        raise ValueError("Reference values do not satisfy their schema: " + "; ".join(errors))
    for field in fields:
        found, value = get_pointer(data, field["path"])
        if not found or value != field["value"]:
            raise ValueError("Parent and child reference values disagree.")


def prepare(root: Path = ROOT) -> Path:
    cases = [
        json.loads(line) for line in (root / "eval/manifest.jsonl").read_text("utf-8").splitlines()
    ]
    output = root / "eval/cache/human-review"
    output.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Corpus review queue",
        "",
        "This pack contains draft work, not approved ground truth.",
        "",
        "For each case, inspect the original file and every expected value and citation. "
        "Complete rights/privacy and template-group review separately. "
        "Do not use calibration/holdout material to tune extraction prompts.",
        "",
        "| Case | Split | Annotation | Original | Draft |",
        "|---|---|---|---|---|",
    ]
    for case in cases:
        draft = json.loads((root / case["annotation_path"]).read_text("utf-8"))
        draft["review_status"] = "pending_human_review"
        draft["source_sha256"] = case["sha256"]
        target = output / f"{case['case_id']}.json"
        existing = json.loads(target.read_text("utf-8")) if target.exists() else {}
        if not existing.get("schema") and not existing.get("expected_fields"):
            target.write_text(json.dumps(draft, indent=2), "utf-8")
        lines.append(
            f"| {case['case_id']} | {case['split']} | {case['annotation_status']} | "
            f"[source](../../../{case['path']}) | [edit draft]({case['case_id']}.json) |"
        )
    index = output / "index.md"
    index.write_text("\n".join(lines) + "\n", "utf-8")
    return index


def record_review(
    root: Path,
    case_id: str,
    input_path: Path,
    reviewer: str,
    *,
    rights_reviewed: bool,
    groups_reviewed: bool,
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", reviewer):
        raise ValueError("Use a stable reviewer identifier, without personal contact data.")
    if not rights_reviewed or not groups_reviewed:
        raise ValueError("Explicit rights/privacy and split-group review are required.")
    manifest_path = root / "eval/manifest.jsonl"
    cases = [json.loads(line) for line in manifest_path.read_text("utf-8").splitlines()]
    case = next(c for c in cases if c["case_id"] == case_id)
    annotation = json.loads(input_path.read_text("utf-8"))
    validate_annotation(annotation, case_id)
    if annotation.get("source_sha256") != case["sha256"]:
        raise ValueError("Review must identify the exact source checksum.")
    if hashlib.sha256((root / case["path"]).read_bytes()).hexdigest() != case["sha256"]:
        raise ValueError("The reviewed original has changed.")
    annotation.update(
        review_status="reviewed", reviewer_id=reviewer, reviewed_at=datetime.now(UTC).isoformat()
    )
    # Keep imported payloads and arbitrary reviewer scratch metadata out of git.
    annotation = {
        key: annotation[key]
        for key in (
            "case_id",
            "schema",
            "instructions",
            "expected_fields",
            "review_status",
            "reviewer_id",
            "reviewed_at",
            "source_sha256",
        )
        if key in annotation
    }
    target = root / "eval/annotations" / f"{case_id}.json"
    if not target.resolve().is_relative_to((root / "eval/annotations").resolve()):
        raise ValueError("Invalid case identifier.")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(annotation, indent=2, ensure_ascii=False) + "\n"
    target.write_bytes(text.encode("utf-8"))
    case.update(
        annotation_path=target.relative_to(root).as_posix(),
        annotation_status="reviewed",
        annotation_review="reviewed",
        rights_status="reviewed",
        group_review="reviewed",
        evaluation_ready=True,
        reviewed_annotation_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    _write_manifest(manifest_path, cases)


def record_ai_review(root: Path, case_id: str, input_path: Path) -> None:
    """Record owner-authorized AI source review without asserting human or rights approval."""
    manifest = root / "eval/manifest.jsonl"
    cases = [json.loads(line) for line in manifest.read_text("utf-8").splitlines()]
    case = next(c for c in cases if c["case_id"] == case_id)
    annotation = json.loads(input_path.read_text("utf-8"))
    validate_annotation(annotation, case_id)
    if annotation.get("review_status") != "ai_reviewed" or annotation.get("reviewer_type") != "ai":
        raise ValueError("AI review must be identified explicitly.")
    if not annotation.get("review_notes") or not annotation.get("reviewer_id"):
        raise ValueError("AI reviewer identity and source review notes are required.")
    if annotation.get("source_sha256") != case["sha256"]:
        raise ValueError("AI review must identify the exact source checksum.")
    original = (root / case["path"]).resolve()
    if not original.is_relative_to(root.resolve()):
        raise ValueError("Invalid source path.")
    if hashlib.sha256(original.read_bytes()).hexdigest() != case["sha256"]:
        raise ValueError("The reviewed original has changed.")
    target = root / "eval/downloads/corpus/ai-reviewed" / f"{case_id}.json"
    if not target.resolve().is_relative_to((root / "eval/downloads/corpus/ai-reviewed").resolve()):
        raise ValueError("Invalid case identifier.")
    target.parent.mkdir(parents=True, exist_ok=True)
    annotation["reviewed_at"] = datetime.now(UTC).isoformat()
    text = json.dumps(annotation, ensure_ascii=False, indent=2) + "\n"
    target.write_bytes(text.encode("utf-8"))
    case.update(
        annotation_path=target.relative_to(root).as_posix(),
        annotation_status="ai_reviewed",
        annotation_review="ai_source_review",
        evaluation_ready=False,
        ai_reviewed_annotation_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    _write_manifest(manifest, cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    ai_review = sub.add_parser("record-ai-review")
    ai_review.add_argument("--case-id", required=True)
    ai_review.add_argument("--input", type=Path, required=True)
    approve = sub.add_parser("record-review")
    approve.add_argument("--case-id", required=True)
    approve.add_argument("--input", type=Path, required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--rights-reviewed", action="store_true")
    approve.add_argument("--groups-reviewed", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
        print("Prepared eval/cache/human-review/index.md; no labels were approved.")
    elif args.command == "record-ai-review":
        record_ai_review(ROOT, args.case_id, args.input)
        print("Recorded AI source review locally; human/rights approval remains unchanged.")
    else:
        record_review(
            ROOT,
            args.case_id,
            args.input,
            args.reviewer,
            rights_reviewed=args.rights_reviewed,
            groups_reviewed=args.groups_reviewed,
        )
        print("Recorded the supplied human review. Run corpus validation and inspect the diff.")


if __name__ == "__main__":
    main()
