from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import hashlib
import json
import math
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_idp.adapters.inbound.http.dependencies import AppContainer, build_container
from ai_idp.application.use_cases.request_extraction import build_pipeline_config
from ai_idp.domain.enums import JobStatus
from ai_idp.domain.models import ExtractionResult
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
    allow_draft: bool = False,
) -> list[dict[str, Any]]:
    if allow_draft and split != "development":
        raise ValueError("Draft diagnostics are restricted to the development split.")
    cases = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if case_ids and item["case_id"] not in case_ids:
            continue
        if sources and item.get("source") not in sources:
            continue
        if item.get("split") != split:
            continue
        if not allow_draft and not item.get("evaluation_ready"):
            continue
        if annotated_only and not item.get("annotation_path"):
            continue
        cases.append(item)
        if limit is not None and len(cases) >= limit:
            break
    if case_ids and set(case_ids) != {c["case_id"] for c in cases}:
        raise ValueError(
            "Requested cases are missing, unreviewed, or outside the selected split/limit."
        )
    return cases


def percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lo, hi = math.floor(position), math.ceil(position)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo), 2)


def aggregate(cases: list[CaseEvaluationSummary]) -> dict[str, Any]:
    total = sum(c.fields_total for c in cases)
    expected_units = sum(c.evidence_units_expected for c in cases)
    all_units = sum(c.units_total for c in cases)
    confusion: Counter[str] = Counter()
    for case in cases:
        confusion.update(case.verification_confusion)
    return {
        "cases_count": len(cases),
        "fields_total": total,
        "exact_accuracy": sum(c.exact_matches for c in cases) / total if total else None,
        "normalized_accuracy": sum(c.normalized_matches for c in cases) / total if total else None,
        "field_evidence_match_rate": sum(c.evidence_matches for c in cases) / total
        if total
        else None,
        "routing_evidence_recall": (
            sum(c.evidence_units_selected for c in cases) / expected_units
            if expected_units
            else None
        ),
        "selection_fraction": sum(c.selected_units for c in cases) / all_units
        if all_units
        else None,
        "selected_unit_precision": (
            sum(c.evidence_units_selected for c in cases) / sum(c.selected_units for c in cases)
            if sum(c.selected_units for c in cases)
            else None
        ),
        "routing_false_negative_units": sum(
            c.evidence_units_expected - c.evidence_units_selected for c in cases
        ),
        "false_supported_count": sum(c.false_supported_count for c in cases),
        "verification_confusion": dict(confusion),
        "recovered_fields": sum(c.recovered_fields for c in cases),
        "escalated_fields": sum(c.escalated_fields for c in cases),
        "failures": sum(c.status == "failed" for c in cases),
        "unresolved_cases": sum(c.status == "completed_with_unresolved" for c in cases),
        "schema_errors": sum(not c.schema_valid for c in cases),
        "llm_calls": sum(c.llm_calls for c in cases),
        "estimated_cost_usd": round(sum(c.estimated_cost_usd for c in cases), 8),
        "end_to_end_latency_ms_p50": percentile([c.latency_ms for c in cases], 0.5),
        "end_to_end_latency_ms_p95": percentile([c.latency_ms for c in cases], 0.95),
    }


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Corpus path escapes the evaluation root.")
    return path


async def run_evaluation_suite(
    container: AppContainer,
    cases: list[dict[str, Any]],
    *,
    profiles: list[str] | None = None,
    root_dir: Path = ROOT,
    allow_draft: bool = False,
    max_total_cost_usd: float = 1.0,
    pipeline_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not cases or max_total_cost_usd <= 0:
        raise ValueError("A nonempty case selection and positive suite budget are required.")
    active_profiles = list(dict.fromkeys(profiles or ["default"]))
    annotations = {}
    for item in cases:
        if allow_draft and item.get("split") != "development":
            raise ValueError("Draft diagnostics are restricted to development cases.")
        annotation_bytes = _safe_path(root_dir, item["annotation_path"]).read_bytes()
        annotation = json.loads(annotation_bytes)
        if item.get("annotation_status") == "ai_reviewed" and (
            hashlib.sha256(annotation_bytes).hexdigest()
            != item.get("ai_reviewed_annotation_sha256")
            or annotation.get("source_sha256") != item["sha256"]
            or annotation.get("review_status") != "ai_reviewed"
            or annotation.get("reviewer_type") != "ai"
        ):
            raise ValueError("AI source review fingerprint or provenance mismatch.")
        if not allow_draft and (
            not item.get("evaluation_ready") or annotation.get("review_status") != "reviewed"
        ):
            raise ValueError("Benchmark runs require reviewed, evaluation-ready annotations.")
        if not annotation.get("schema") or not annotation.get("expected_fields"):
            raise ValueError(f"Case '{item['case_id']}' has no extraction annotation.")
        if annotation.get("case_id") != item["case_id"]:
            raise ValueError("Annotation identity mismatch.")
        digest = hashlib.sha256(_safe_path(root_dir, item["path"]).read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError("Source checksum mismatch.")
        annotations[item["case_id"]] = annotation
    configurations = {
        p: build_pipeline_config(container.settings, p, pipeline_overrides).model_dump(mode="json")
        for p in active_profiles
    }
    summaries: list[CaseEvaluationSummary] = []
    spent = 0.0
    stopped_for_budget = False
    for item in cases:
        annotation = annotations[item["case_id"]]
        file_path = _safe_path(root_dir, item["path"])
        prepare_start = time.perf_counter()
        preparation_failure = None
        doc, units = None, []
        try:
            doc = await asyncio.to_thread(
                container.ingest_use_case.execute,
                raw_bytes=file_path.read_bytes(),
                filename=file_path.name,
                eager_normalize=True,
            )
            units = container.job_repo.get_units(doc.document_id)
        except Exception as exc:
            doc = None
            preparation_failure = getattr(exc, "code", type(exc).__name__)
        preparation_ms = int((time.perf_counter() - prepare_start) * 1000)
        for profile in active_profiles:
            remaining = max_total_cost_usd - spent
            if remaining <= 0:
                stopped_for_budget = True
                break
            started = time.perf_counter()
            failure = preparation_failure
            job = None
            result = ExtractionResult(job_id="", status=JobStatus.FAILED)
            try:
                if doc is None:
                    raise RuntimeError("Source preparation failed.")
                job = container.request_extraction_use_case.execute(
                    document_id=doc.document_id,
                    schema_json=annotation["schema"],
                    instructions=annotation.get("instructions", ""),
                    model_profile=profile,
                    config_overrides={
                        **(pipeline_overrides or {}),
                        "max_job_estimated_cost_usd": min(
                            remaining, container.settings.max_job_estimated_cost_usd
                        ),
                    },
                )
                with container.telemetry.span(
                    "evaluation.case",
                    {
                        "case_id": item["case_id"],
                        "profile": profile,
                        "job_id": job.job_id,
                    },
                ):
                    result = await container.pipeline_service.execute_job(job.job_id)
            except Exception as exc:
                if job is not None:
                    persisted = container.job_repo.get_job(job.job_id)
                    result = ExtractionResult(
                        job_id=job.job_id, status=JobStatus.FAILED, usage=persisted.usage
                    )
                failure = failure or getattr(exc, "code", type(exc).__name__)
            summary = score_extraction_result(
                case_id=item["case_id"],
                source=item.get("source", "unknown"),
                doc_format=item.get("format", "unknown"),
                split=item["split"],
                model_profile=profile,
                result=result,
                expected_fields=annotation["expected_fields"],
            )
            summary.latency_ms = preparation_ms + int((time.perf_counter() - started) * 1000)
            summary.preparation_ms = preparation_ms
            summary.failure_reason = failure
            summary.units_total = len(units)
            selected = (
                container.result_repo.load_step(job.job_id, "routing:selection") if job else {}
            ) or {}
            selected_ids = set(selected.get("selected_unit_ids", []))
            if profile in ("always_vision", "text_only"):
                selected_ids = {u.unit_id for u in units}
            expected_ids = set()
            for field in annotation["expected_fields"]:
                for source in field.get("sources", []):
                    if source.get("unit_id"):
                        expected_ids.add(source["unit_id"])
                    elif source.get("locator"):
                        expected_ids.update(
                            u.unit_id
                            for u in units
                            if all(
                                u.source_locator.get(k) == v for k, v in source["locator"].items()
                            )
                        )
            summary.evidence_units_expected = len(expected_ids)
            summary.evidence_units_selected = len(expected_ids & selected_ids)
            summary.selected_units = len(selected_ids)
            summaries.append(summary)
            spent += result.usage.estimated_cost_usd
        if stopped_for_budget:
            break
    by_profile = {
        p: aggregate([s for s in summaries if s.model_profile == p]) for p in active_profiles
    }
    by_source = {
        f"{p}:{source}": aggregate(
            [s for s in summaries if s.model_profile == p and s.source == source]
        )
        for p in active_profiles
        for source in sorted({s.source for s in summaries})
    }
    by_format = {
        f"{p}:{fmt}": aggregate([s for s in summaries if s.model_profile == p and s.format == fmt])
        for p in active_profiles
        for fmt in sorted({s.format for s in summaries})
    }
    run_id = f"eval_{uuid.uuid4().hex[:12]}"
    corpus_fingerprint = hashlib.sha256(
        json.dumps(
            [
                {
                    "case_id": c["case_id"],
                    "sha256": c["sha256"],
                    "annotation_sha256": hashlib.sha256(
                        json.dumps(annotations[c["case_id"]], sort_keys=True).encode()
                    ).hexdigest(),
                }
                for c in cases
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    config_hash = hashlib.sha256(json.dumps(configurations, sort_keys=True).encode()).hexdigest()
    report = {
        "evaluation_run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "report_kind": "development_diagnostic" if allow_draft else "reviewed_benchmark",
        "benchmark_claims_allowed": not allow_draft,
        "reference_review_status_counts": dict(
            Counter(a.get("review_status", "unspecified") for a in annotations.values())
        ),
        "configurations": configurations,
        "configuration_hash": config_hash,
        "corpus_fingerprint": corpus_fingerprint,
        "budget": {
            "estimated_usd": max_total_cost_usd,
            "stopped": stopped_for_budget,
            "provider_billing_cap": False,
        },
        "summary_by_profile": by_profile,
        "summary_by_source": by_source,
        "summary_by_format": by_format,
        "cases": [dataclasses.asdict(s) for s in summaries],
    }
    container.result_repo.save_evaluation_run(
        run_id=run_id,
        dataset_ref=corpus_fingerprint,
        config_hash=config_hash,
        status="budget_stopped" if stopped_for_budget else "completed",
        metrics=by_profile,
    )
    out_dir = root_dir / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{run_id}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (out_dir / f"{run_id}.csv").open("w", newline="", encoding="utf-8") as stream:
        keys = [
            "case_id",
            "source",
            "format",
            "split",
            "model_profile",
            "status",
            "fields_total",
            "normalized_matches",
            "false_supported_count",
            "estimated_cost_usd",
            "latency_ms",
            "failure_reason",
        ]
        writer = csv.DictWriter(stream, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["cases"])
    lines = [
        f"# {report['report_kind']}",
        "",
        "Draft diagnostics are not a reviewed benchmark."
        if allow_draft
        else "Scored against reviewed annotations.",
        "",
        "| Profile | Cases | Field accuracy | False supported | Cost (estimated USD) | p95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for profile, metrics in by_profile.items():
        lines.append(
            f"| {profile} | {metrics['cases_count']} | {metrics['normalized_accuracy']} | "
            f"{metrics['false_supported_count']} | {metrics['estimated_cost_usd']} | "
            f"{metrics['end_to_end_latency_ms_p95']} |"
        )
    (out_dir / f"{run_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Run explicitly budgeted AI-IDP model evaluation.")
    parser.add_argument("--live", action="store_true", help="Authorize real provider requests")
    parser.add_argument("--allow-draft", action="store_true", help="Development diagnostics only")
    parser.add_argument("--max-total-cost-usd", type=float, required=True)
    parser.add_argument(
        "--split", choices=["development", "calibration", "holdout"], default="development"
    )
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--profile", action="append", dest="profiles")
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--unbatched-questions", action="store_true")
    parser.add_argument("--relevance-strategy", choices=["generative", "decisions"])
    parser.add_argument("--relevance-batch-units", type=int)
    parser.add_argument("--parallel-decision-batches", type=int)
    args = parser.parse_args()
    if not args.live:
        parser.error("Real model calls require --live and an explicit total budget.")
    cases = load_manifest_cases(
        case_ids=args.case_ids,
        sources=args.sources,
        split=args.split,
        limit=args.limit,
        allow_draft=args.allow_draft,
    )
    overrides = {}
    if args.unbatched_questions:
        overrides["batch_relevance_questions"] = False
    if args.relevance_strategy:
        overrides["relevance_strategy"] = args.relevance_strategy
    if args.relevance_batch_units is not None:
        overrides["relevance_batch_units"] = args.relevance_batch_units
    if args.parallel_decision_batches is not None:
        overrides["max_parallel_decision_batches"] = args.parallel_decision_batches
    report = await run_evaluation_suite(
        build_container(),
        cases,
        profiles=args.profiles,
        allow_draft=args.allow_draft,
        max_total_cost_usd=args.max_total_cost_usd,
        pipeline_overrides=overrides or None,
    )
    print(
        json.dumps(
            {
                "evaluation_run_id": report["evaluation_run_id"],
                "report_kind": report["report_kind"],
                "summary_by_profile": report["summary_by_profile"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(_async_main())
