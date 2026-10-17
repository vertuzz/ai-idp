"""Assemble the 120-file inventory and honest annotation-review work queue."""

import json
import re
from collections import Counter
from datetime import UTC, datetime

from scripts.prepare_cord_preview import ROOT, sha256, write_json


def evidence_for_cord(annotation, category):
    evidence = []
    for line in annotation.get("valid_line", []):
        if line.get("category") == category:
            evidence.append(
                {
                    "unit_id": "frame_000001",
                    "locator": {"frame_index": 0},
                    "quote": " ".join(word["text"] for word in line["words"]),
                    "word_quadrilaterals": [word["quad"] for word in line["words"]],
                }
            )
    return evidence


def cord_annotation(case):
    upstream = json.loads((ROOT / case["upstream_annotation"]).read_text(encoding="utf-8"))
    parsed = upstream["gt_parse"]
    properties, fields = {}, []
    # Preserve amount spelling. Missing upstream labels do not prove source absence.
    for group, field in [
        ("total", "total_price"),
        ("total", "cashprice"),
        ("total", "changeprice"),
        ("sub_total", "subtotal_price"),
        ("sub_total", "tax_price"),
        ("sub_total", "service_price"),
    ]:
        value = parsed.get(group, {}).get(field)
        if value is not None:
            properties[field] = {
                "type": "string",
                "description": f"Receipt {group}.{field}; preserve printed formatting.",
            }
            fields.append(
                {
                    "path": "/" + field,
                    "value": value,
                    "sources": evidence_for_cord(upstream, group + "." + field),
                }
            )
    menus = parsed.get("menu", [])
    menus = menus if isinstance(menus, list) else [menus]
    if menus:
        properties["items"] = {
            "type": "array",
            "description": (
                "Top-level receipt line items in printed order; "
                "nested add-ons are outside this starter schema."
            ),
            "items": {
                "type": "object",
                "properties": {
                    key: {"type": ["string", "null"]} for key in ["name", "quantity", "price"]
                },
                "required": ["name", "quantity", "price"],
                "additionalProperties": False,
            },
        }
        for index, menu in enumerate(menus):
            for target, source in [("name", "nm"), ("quantity", "cnt"), ("price", "price")]:
                if source in menu:
                    fields.append(
                        {
                            "path": f"/items/{index}/{target}",
                            "value": menu[source],
                            # Matching lines are candidates; item evidence needs review.
                            "sources": evidence_for_cord(upstream, "menu." + source),
                            "evidence_review": "item_to_line_mapping_pending",
                        }
                    )
    return {
        "schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "instructions": (
            "Read the receipt as printed. Do not normalize punctuation or infer missing quantities."
        ),
        "expected_fields": fields,
        "origin": "upstream_labels_adapted_without_human_review",
        "known_limitations": [
            "Upstream item groups and word evidence require adjudication.",
            "Unlabeled fields are unknown, not asserted absent.",
        ],
    }


def synthetic_annotation(case):
    params = json.loads((ROOT / case["parameters"]).read_text(encoding="utf-8"))
    fields = []
    properties = {}
    for name in ["record_id", "issue_date", "period", "currency", "net_total", "approved_total"]:
        value = params[name]
        properties[name] = {
            "type": "integer" if isinstance(value, int) else "string",
            "description": (
                f"Final current-period {name.replace('_', ' ')}; "
                "exclude historical and superseded drafts."
            ),
        }
        if case["format"] == "docx":
            source = {
                "locator": {
                    "heading": "Current period summary"
                    if params["split"] == "development"
                    else "Laboratory batch register"
                    if params["split"] == "calibration"
                    else "Settlement authorisation"
                },
                "locator_status": "semantic_block_id_pending",
            }
        else:
            page = 3 if params["kind"] == "mixed" else 1
            source = {"unit_id": f"page_{page:06d}", "locator": {"page_number": page}}
        fields.append(
            {"path": "/" + name, "value": value, "sources": [dict(source, quote=str(value))]}
        )
    properties["purchase_order_reference"] = {
        "type": ["string", "null"],
        "description": "Purchase order reference; null if not provided.",
    }
    fields.append(
        {
            "path": "/purchase_order_reference",
            "value": None,
            "sources": [],
            "absence": "deliberately_omitted_by_generator",
        }
    )
    if params["kind"] == "docx":
        properties["inspection_status"] = {
            "type": "string",
            "description": "Inspection status in the embedded label image.",
        }
        fields.append(
            {
                "path": "/inspection_status",
                "value": "PASS",
                "sources": [
                    {"locator": {"embedded_image": "image1.png"}, "quote": "Inspection status PASS"}
                ],
            }
        )
    return {
        "schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "instructions": (
            "Extract final current-period values, "
            "ignoring historical currencies and superseded drafts."
        ),
        "expected_fields": fields,
        "origin": "deterministic_generator_parameters",
        "known_limitations": [
            "Human answer-key review is pending; DOCX block IDs await ingestion contract."
        ],
    }


def main():
    cases = []
    output = ROOT / "eval/downloads/corpus/annotations"
    output.mkdir(parents=True, exist_ok=True)
    for source in ["doclaynet", "cord", "government", "synthetic"]:
        cases.extend(
            json.loads((ROOT / f"eval/{source}-selection.json").read_text(encoding="utf-8"))
        )
    for case in cases:
        case["bytes"] = (ROOT / case["path"]).stat().st_size
        if case["source"] == "doclaynet":
            parent = case["group_id"].removeprefix("doclaynet-parent:")
            case["group_id"] = "doclaynet-parent:" + re.sub(r"[^a-z0-9]", "", parent.casefold())
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
                    "todo": (
                        "Define 3-8 caller-like targets; "
                        "annotate values and original page/block evidence."
                    ),
                }
            )
        target = output / f"{case['case_id']}.json"
        if target.exists():
            annotation = json.loads(target.read_text(encoding="utf-8"))
            if annotation["case_id"] != case["case_id"]:
                raise ValueError("Existing annotation belongs to another case")
        else:
            write_json(target, annotation)
        case["annotation_path"] = target.relative_to(ROOT).as_posix()
        case["annotation_status"] = "draft" if annotation["expected_fields"] else "not_annotated"
        case["annotation_review"] = "pending_human_review"
        case["evaluation_ready"] = False
        case["downloaded_at"] = datetime.now(UTC).isoformat()
        if "upstream_annotation" in case:
            case["upstream_annotation_sha256"] = sha256(ROOT / case["upstream_annotation"])
    cases.sort(key=lambda c: (c["source"], c["split"], c["case_id"]))
    manifest = ROOT / "eval/manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases), encoding="utf-8"
    )
    quotas = {"doclaynet": 7, "cord_v2": 6, "gov_uk_pdf": 4, "gov_uk_docx": 3, "synthetic": 4}
    preview = []
    for source, count in quotas.items():
        available = [c for c in cases if c["source"] == source and c["split"] == "development"]
        chosen, categories = [], set()
        if source in {"doclaynet", "synthetic"}:
            for case in available:
                category = case.get("category", case["tags"][0])
                if category not in categories:
                    categories.add(category)
                    chosen.append(case["case_id"])
        chosen.extend(c["case_id"] for c in available if c["case_id"] not in chosen)
        preview.extend(chosen[:count])
    write_json(
        ROOT / "eval/preview-selection.json",
        {"status": "files_available_annotations_pending", "case_ids": preview},
    )
    states = dict(Counter(c["annotation_status"] for c in cases))
    print(f"Assembled {len(cases)} cases; annotation states: {states}")


if __name__ == "__main__":
    main()
