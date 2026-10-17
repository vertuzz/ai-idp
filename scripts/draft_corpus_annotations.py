"""Author budgeted annotation-only drafts; never score, tune or approve benchmark labels."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ai_idp.adapters.inbound.http.dependencies import build_container
from ai_idp.application.ports.protocols import UnitInputPayload
from ai_idp.application.services.batching import unit_batches
from ai_idp.domain.enums import Modality, UnitKind
from ai_idp.domain.field_paths import escape_segment
from ai_idp.domain.models import DocumentUnit
from ai_idp.domain.schema_normalizer import normalize_extraction_schema
from scripts.review_corpus import validate_annotation

ROOT = Path(__file__).resolve().parents[1]
FIELD_PROPERTIES = {
    "name": {"type": "string"},
    "description": {"type": "string"},
    "value_json": {"type": "string", "description": "Value encoded as a JSON literal"},
    "unit_ids": {"type": "array", "items": {"type": "string"}},
    "quote": {"type": "string", "description": "Exact original supporting words"},
}
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": FIELD_PROPERTIES,
                "required": list(FIELD_PROPERTIES),
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}
GUIDANCE = (
    "Design a document extraction review task with 4 to 8 useful, objectively checkable "
    "scalar fields from this document. Select fields using the actual document content. "
    "Prefer identifiers, titles, named entities, dates, significant counts and amounts "
    "with their exact meaning. For multiple pages, choose evidence across distinct pages. "
    "Do not choose page numbers, filenames, artificial unit IDs or processing metadata as values. "
    "Use simple unique English snake_case names. Preserve printed string formatting. "
    "Each value_json must be a JSON string, number, boolean or null; encode printed amounts "
    "as JSON strings. Cite exact original unit_ids and an exact supporting quote. "
    "These are unreviewed annotation drafts for human correction, not ground truth."
)


def make_annotation(case_id, fields, units):
    properties, expected = {}, []
    known = {u.unit_id: u for u in units}
    incomplete = 0
    for field in fields:
        if not isinstance(field, dict) or any(field.get(key) is None for key in FIELD_PROPERTIES):
            incomplete += 1
            continue
        name = field["name"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or name in properties:
            raise ValueError("Draft field names must be unique simple identifiers.")
        value = json.loads(field["value_json"])
        if isinstance(value, (list, dict)):
            incomplete += 1
            continue
        kind = (
            "null"
            if value is None
            else "boolean"
            if isinstance(value, bool)
            else "integer"
            if isinstance(value, int)
            else "number"
            if isinstance(value, float)
            else "string"
        )
        properties[name] = {"type": kind, "description": field["description"]}
        if any(uid not in known for uid in field["unit_ids"]):
            raise ValueError("Draft cites an unknown source unit.")
        expected.append(
            {
                "path": "/" + escape_segment(name),
                "value": value,
                "sources": [
                    {"unit_id": uid, "locator": known[uid].source_locator, "quote": field["quote"]}
                    for uid in field["unit_ids"]
                ],
            }
        )
    annotation = {
        "case_id": case_id,
        "review_status": "pending_human_review",
        "schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "instructions": "Extract the specified values as printed, using the requested context.",
        "expected_fields": expected,
        "draft_warnings": [f"Skipped {incomplete} incomplete or non-scalar candidate fields"]
        if incomplete
        else [],
    }
    validate_annotation(annotation, case_id)
    return annotation


async def run(max_cost: float, limit: int | None, splits: list[str] | None = None):
    container = build_container()
    manifest = ROOT / "eval/manifest.jsonl"
    cases = [json.loads(line) for line in manifest.read_text("utf-8").splitlines()]
    pending = [
        c
        for c in cases
        if c["split"] in (splits or ["development"]) and c["annotation_status"] == "not_annotated"
    ]
    if limit:
        pending = pending[:limit]
    spent, calls, outcomes = 0.0, 0, []
    spec = normalize_extraction_schema(DRAFT_SCHEMA, GUIDANCE)

    async def call(inputs, instructions=GUIDANCE):
        nonlocal spent, calls
        if spent >= max_cost:
            raise ValueError("Draft authoring estimated budget exhausted.")
        result = await container.extraction_engine.extract_fields(
            job_id="draft_" + uuid.uuid4().hex[:12],
            spec=spec.model_copy(update={"instructions": instructions}),
            target_fields=spec.fields,
            unit_inputs=inputs,
            model_id=container.settings.extraction_model,
            stage_name="annotation_draft",
        )
        spent += result.usage.estimated_cost_usd
        calls += result.usage.call_count
        return result.data["fields"]

    for case in pending:
        if spent >= max_cost:
            break
        try:
            path = ROOT / case["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != case["sha256"]:
                raise ValueError("Source checksum mismatch.")
            doc = await asyncio.to_thread(
                container.ingest_use_case.execute, raw_bytes=path.read_bytes(), filename=path.name
            )
            units = container.job_repo.get_units(doc.document_id)
            payloads = await asyncio.to_thread(
                container.pipeline_service._load_unit_payloads, units
            )
            inputs = [
                (
                    p,
                    Modality.TEXT_AND_VISION
                    if p.native_text and p.image_bytes
                    else Modality.VISION
                    if p.image_bytes
                    else Modality.TEXT,
                )
                for p in payloads
            ]
            batches = unit_batches(
                inputs, max_units=12, max_bytes=container.settings.max_model_input_bytes
            )
            candidates = [await call(batch) for batch in batches]
            while len(candidates) > 1:
                summaries = [
                    (
                        UnitInputPayload(
                            unit=DocumentUnit(
                                unit_id=f"draft_{i}",
                                document_id=doc.document_id,
                                ordinal=i + 1,
                                kind=UnitKind.DOCX_BLOCK,
                            ),
                            native_text=json.dumps(fields),
                        ),
                        Modality.TEXT,
                    )
                    for i, fields in enumerate(candidates)
                ]
                groups = unit_batches(
                    summaries, max_units=12, max_bytes=container.settings.max_model_input_bytes
                )
                if len(groups) >= len(candidates):
                    raise ValueError("Draft candidate merge exceeds the input limit.")
                candidates = [
                    await call(
                        group,
                        GUIDANCE + " Select 4 to 8 diverse fields from "
                        "these source-grounded drafts. Preserve their original unit IDs, values "
                        "and quotes; never cite draft_* IDs.",
                    )
                    for group in groups
                ]
            annotation = make_annotation(case["case_id"], candidates[0], units)
            annotation.update(
                draft_authoring_model=container.settings.extraction_model,
                draft_created_at=datetime.now(UTC).isoformat(),
            )
            target = ROOT / case["annotation_path"]
            previous = json.loads(target.read_text("utf-8"))
            if previous.get("schema") or previous.get("expected_fields"):
                raise ValueError("Existing annotation content must not be overwritten.")
            target.write_text(json.dumps(annotation, indent=2, ensure_ascii=False), "utf-8")
            case["annotation_status"] = "draft"
            temporary_manifest = ROOT / "eval/downloads/manifest-authoring.tmp"
            temporary_manifest.write_text(
                "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", "utf-8"
            )
            temporary_manifest.replace(manifest)
            outcomes.append(
                {
                    "case_id": case["case_id"],
                    "status": "draft_authored",
                    "fields": len(annotation["expected_fields"]),
                }
            )
        except Exception as exc:
            spent += getattr(exc, "reported_cost", 0.0)
            outcomes.append(
                {"case_id": case["case_id"], "status": "failed", "error_type": type(exc).__name__}
            )
        print(json.dumps({**outcomes[-1], "suite_estimated_cost_usd": round(spent, 6)}), flush=True)
    output = ROOT / "eval/results" / f"draft_authoring_{uuid.uuid4().hex[:10]}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"estimated_cost_usd": spent, "calls": calls, "outcomes": outcomes}, indent=2),
        "utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-total-cost-usd", type=float, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--split", action="append", choices=["development", "calibration", "holdout"]
    )
    parser.add_argument(
        "--annotation-only",
        action="store_true",
        help="Explicitly authorize annotation of protected splits; never score/tune",
    )
    args = parser.parse_args()
    if not args.live or args.max_total_cost_usd <= 0:
        parser.error("Use --live with a positive explicit estimated budget.")
    if any(split != "development" for split in (args.split or [])) and not args.annotation_only:
        parser.error("Protected splits require explicit --annotation-only authorization.")
    asyncio.run(run(args.max_total_cost_usd, args.limit, args.split))


if __name__ == "__main__":
    main()
