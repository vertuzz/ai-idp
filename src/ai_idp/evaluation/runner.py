from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_idp.adapters.inbound.http.dependencies import AppContainer, build_container
from ai_idp.evaluation.metrics import CaseEvaluationSummary, score_extraction_result

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "eval" / "manifest.jsonl"


def load_manifest_cases(
    manifest_path: Path = MANIFEST_PATH,
    *,
    case_ids: list[str] | None = None,
    sources: list[str] | None = None,
    split: str = "development",
    annotated_only: bool = True,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    wanted_ids = set(case_ids) if case_ids else None
    wanted_sources = set(sources) if sources else None

    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if wanted_ids is not None and item["case_id"] not in wanted_ids:
            continue
        if wanted_sources is not None and item.get("source") not in wanted_sources:
            continue
        if split and wanted_ids is None and item.get("split") != split:
            continue
        if annotated_only and not item.get("annotation_path"):
            continue
        cases.append(item)
        if limit is not None and len(cases) >= limit:
            break
    return cases


async def run_evaluation_suite(
    container: AppContainer,
    cases: list[dict[str, Any]],
    *,
    profiles: list[str] | None = None,
    root_dir: Path = ROOT,
) -> dict[str, Any]:
    active_profiles = profiles or ["default"]
    summaries: list[CaseEvaluationSummary] = []

    for item in cases:
        case_id = item["case_id"]
        file_path = root_dir / item["path"]
        annotation_rel = item.get("annotation_path")
        if not annotation_rel:
            continue
        annotation_path = root_dir / annotation_rel
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))

        raw_bytes = file_path.read_bytes()
        doc = container.ingest_use_case.execute(
            raw_bytes=raw_bytes,
            filename=file_path.name,
            eager_normalize=True,
        )

        # Reuse the same prepared document across all requested model profiles
        for profile in active_profiles:
            job = container.request_extraction_use_case.execute(
                document_id=doc.document_id,
                schema_json=annotation["schema"],
                instructions=annotation.get("instructions", ""),
                model_profile=profile,
            )
            result = await container.pipeline_service.execute_job(job.job_id)

            summary = score_extraction_result(
                case_id=case_id,
                source=item.get("source", "unknown"),
                doc_format=item.get("format", "unknown"),
                split=item.get("split", "development"),
                model_profile=profile,
                result=result,
                expected_fields=annotation.get("expected_fields", []),
            )
            summaries.append(summary)

    by_profile: dict[str, dict[str, Any]] = {}
    for prof in active_profiles:
        prof_cases = [s for s in summaries if s.model_profile == prof]
        total_fields = sum(s.fields_total for s in prof_cases)
        exact_matches = sum(s.exact_matches for s in prof_cases)
        norm_matches = sum(s.normalized_matches for s in prof_cases)
        ev_matches = sum(s.evidence_matches for s in prof_cases)
        false_sup = sum(s.false_supported_count for s in prof_cases)
        total_cost = round(sum(s.estimated_cost_usd for s in prof_cases), 6)
        total_calls = sum(s.llm_calls for s in prof_cases)
        by_profile[prof] = {
            "cases_count": len(prof_cases),
            "fields_total": total_fields,
            "exact_accuracy": round(exact_matches / total_fields, 4) if total_fields else 0.0,
            "normalized_accuracy": round(norm_matches / total_fields, 4) if total_fields else 0.0,
            "evidence_recall": round(ev_matches / total_fields, 4) if total_fields else 0.0,
            "false_supported_count": false_sup,
            "llm_calls": total_calls,
            "estimated_cost_usd": total_cost,
        }

    run_id = f"eval_{uuid.uuid4().hex[:12]}"
    config_hash = hashlib.sha256(
        json.dumps(
            {
                "decision_model": container.settings.decision_model,
                "extraction_model": container.settings.extraction_model,
                "escalation_model": container.settings.escalation_model,
                "profiles": active_profiles,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]

    report = {
        "evaluation_run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "models": {
            "decision_model": container.settings.decision_model,
            "extraction_model": container.settings.extraction_model,
            "escalation_model": container.settings.escalation_model,
        },
        "summary_by_profile": by_profile,
        "cases": [dataclasses.asdict(s) for s in summaries],
    }

    if hasattr(container.result_repo, "save_evaluation_run"):
        container.result_repo.save_evaluation_run(
            run_id=run_id,
            dataset_ref=f"manifest:{len(cases)}_cases",
            config_hash=config_hash,
            status="completed",
            metrics=report["summary_by_profile"],
        )

    out_dir = root_dir / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{run_id}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Run AI-IDP evaluation suite on corpus cases.")
    parser.add_argument(
        "--case-id", action="append", dest="case_ids", help="Specific case_id(s) to run"
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        help="Filter by source (e.g. synthetic, cord_v2)",
    )
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Model profiles (default, always_vision, text_only)",
    )
    parser.add_argument("--limit", type=int, default=4, help="Maximum number of cases to run")
    args = parser.parse_args()

    container = build_container()
    cases = load_manifest_cases(
        case_ids=args.case_ids,
        sources=args.sources,
        limit=args.limit,
    )
    report = await run_evaluation_suite(
        container,
        cases,
        profiles=args.profiles or ["default"],
    )
    print(json.dumps(report["summary_by_profile"], indent=2))
    for c in report["cases"]:
        print(
            f"[{c['case_id']}] profile={c['model_profile']} status={c['status']} "
            f"exact={c['exact_matches']}/{c['fields_total']} "
            f"norm={c['normalized_matches']}/{c['fields_total']} "
            f"evidence={c['evidence_matches']}/{c['fields_total']} "
            f"calls={c['llm_calls']} cost=${c['estimated_cost_usd']:.5f}"
        )


if __name__ == "__main__":
    asyncio.run(_async_main())
