"""Restore the selected 120-file corpus; verify existing files before reusing them."""

import json
import shutil

from scripts.prepare_cord_preview import ROOT, download, sha256, write_json


def verify_file(path, expected):
    if path.exists() and sha256(path) != expected:
        raise ValueError(f"Existing corpus asset is modified: {path}")
    return path.exists()


def main():
    cases = [
        json.loads(line)
        for line in (ROOT / "eval/manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    missing_cord = False
    missing_doclaynet = False
    for case in cases:
        path = ROOT / case["path"]
        present = verify_file(path, case["sha256"])
        if case["source"].startswith("gov_uk_") and not present:
            download(case["source_url"], path, case["sha256"], case["bytes"])
        if case["source"] == "synthetic":
            fixture = ROOT / case["repository_fixture"]
            if not verify_file(fixture, case["sha256"]):
                raise FileNotFoundError(f"Repository fixture missing: {fixture}")
            if not present:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(fixture, path)
            parameters = ROOT / case["parameters"]
            if not parameters.exists():
                shutil.copyfile(fixture.with_suffix(".parameters.json"), parameters)
        for asset in case.get("assets", {}).values():
            if not verify_file(ROOT / asset["path"], asset["sha256"]):
                missing_doclaynet = True
        if "upstream_annotation" in case:
            annotation_present = verify_file(
                ROOT / case["upstream_annotation"], case["upstream_annotation_sha256"]
            )
            if case["source"] == "cord_v2" and (not present or not annotation_present):
                missing_cord = True
            if case["source"] == "doclaynet" and (not present or not annotation_present):
                missing_doclaynet = True
    if missing_cord:
        from scripts.acquire_cord import main as acquire_cord

        acquire_cord()
    if missing_doclaynet:
        from scripts.acquire_doclaynet import main as acquire_doclaynet

        acquire_doclaynet()
    from scripts.assemble_corpus import cord_annotation, synthetic_annotation

    for case in cases:
        target = ROOT / case["annotation_path"]
        if target.exists():
            continue
        if case.get("annotation_status") in ("reviewed", "ai_reviewed"):
            raise FileNotFoundError(
                "A reviewed answer set is missing. Restore its exact bytes from source control "
                "or the local review backup; it cannot be regenerated as a draft."
            )
        annotation = {"case_id": case["case_id"], "review_status": "pending_human_review"}
        if case["source"] == "cord_v2":
            annotation.update(cord_annotation(case))
        elif case["source"] == "synthetic":
            annotation.update(synthetic_annotation(case))
        else:
            annotation.update(
                {
                    "schema": None,
                    "expected_fields": [],
                    "origin": None,
                    "todo": "Define caller-like targets and annotate values/evidence.",
                }
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json(target, annotation)
    from scripts.validate_corpus import validate

    report = validate(cases)
    write_json(ROOT / "eval/corpus-status.json", report)
    if report["errors"]:
        raise ValueError("Corpus verification failed: " + str(report["errors"]))
    print(
        f"Verified {report['documents']}/120 files. "
        f"AI source-reviewed: {report['ai_source_reviewed']}/120. "
        f"Human benchmark-ready: {report['evaluation_ready']}/120."
    )


if __name__ == "__main__":
    main()
