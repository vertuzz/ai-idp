"""Write a browsable catalog from the actual manifest and integrity report."""

import json
from collections import Counter
from pathlib import Path

from scripts.prepare_cord_preview import ROOT


def main():
    cases = [
        json.loads(line)
        for line in (ROOT / "eval/manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    report = json.loads((ROOT / "eval/corpus-status.json").read_text(encoding="utf-8"))
    preview = set(
        json.loads((ROOT / "eval/preview-selection.json").read_text(encoding="utf-8"))["case_ids"]
    )
    lines = [
        "# Candidate corpus v1",
        "",
        "All 120 primary documents are present and pass file integrity checks.",
        "This is a complete file collection with pending annotation review, "
        "not a finished gold benchmark.",
        "",
        "| Source | Files | Development | Calibration | Holdout |",
        "|---|---:|---:|---:|---:|",
    ]
    for source in sorted(report["sources"]):
        selected = [c for c in cases if c["source"] == source]
        counts = Counter(c["split"] for c in selected)
        lines.append(
            f"| {source} | {len(selected)} | {counts['development']} | "
            f"{counts['calibration']} | {counts['holdout']} |"
        )
    mib = sum(report["primary_bytes_by_source"].values()) / 1024**2
    lines.extend(
        [
            "",
            f"Primary originals: **{mib:.1f} MiB**, "
            "excluding image counterparts, labels and cache.",
            "Formats: 70 PDFs, 20 DOCX files and 30 PNG receipts. PDF originals total 611 pages.",
            "DOCX physical pages are not assumed; "
            "semantic block IDs will be assigned during ingestion.",
            "",
            "**Readiness:** 50 draft answer keys, 70 unannotated cases, "
            "0 human-reviewed evaluation-ready cases.",
            "**Splits:** proposed 72/24/24 allocation; recorded groups do not cross splits. "
            "Final template/near-duplicate review remains pending.",
            "**Rights:** dataset/publisher licence references recorded; "
            "external files remain local pending file-specific review.",
            "",
            "A star marks one of the 24 selected development-preview cases. "
            "Each document has a local annotation work file.",
            "See [setup and remaining work](README.md), [manifest](manifest.jsonl) "
            "and [machine validation](corpus-status.json).",
            "",
        ]
    )
    for source in sorted(report["sources"]):
        lines.extend(["## " + source, "", "| Document | Split | Answers |", "|---|---|---|"])
        for case in cases:
            if case["source"] != source:
                continue
            label = case.get("title", case["case_id"])
            label = label.replace("|", " ").replace("[", "(").replace("]", ")")
            if len(label) > 100:
                label = label[:97] + "..."
            document = Path(case["path"]).relative_to("eval").as_posix()
            annotation = Path(case["annotation_path"]).relative_to("eval").as_posix()
            marker = "* " if case["case_id"] in preview else ""
            lines.append(
                f"| {marker}[{label}]({document}) | {case['split']} | "
                f"[{case['annotation_status']}]({annotation}) |"
            )
        lines.append("")
    (ROOT / "eval/CORPUS.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print("Catalog written: eval/CORPUS.md")


if __name__ == "__main__":
    main()
