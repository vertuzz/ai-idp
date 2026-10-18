"""Checkpointed output pages; collections are assembled without a full-list model merge."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, replace
from functools import partial
from typing import Any

from ai_idp.application.ports.protocols import ExtractionBatchResult, VerificationBatchResult
from ai_idp.application.services.record_evidence import anchor_value, scalar_leaves
from ai_idp.domain.enums import VerificationStatus
from ai_idp.domain.errors import DocumentLimitExceededError, ModelOutputLimitExceededError
from ai_idp.domain.field_paths import escape_segment
from ai_idp.domain.models import TargetFieldSpec
from ai_idp.domain.validation import build_token_pattern


def contains_array(node: dict[str, Any]) -> bool:
    types = node.get("type", [])
    return "array" in types or any(contains_array(c) for c in node.get("properties", {}).values())


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:24]


async def extract_partitioned(pipeline: Any, key: str, **kwargs: Any) -> ExtractionBatchResult:
    recovering = kwargs.pop("_recovering", False)
    job = pipeline._job_repo.get_job(kwargs["job_id"])
    config = job.configuration
    data: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    part_count = 0
    total_bytes = 0

    async def field(field: TargetFieldSpec) -> Any:
        nonlocal part_count, total_bytes
        if field.field_type == "object" and contains_array(field.raw_schema):
            assembled: dict[str, Any] = {}
            for name, node in field.raw_schema["properties"].items():
                path = field.path + "/" + escape_segment(name)
                types = node["type"] if isinstance(node["type"], list) else [node["type"]]
                kind = next((t for t in types if t != "null"), "null")
                child = TargetFieldSpec(
                    path=path,
                    name=path,
                    field_type=kind,
                    is_array=kind == "array",
                    raw_schema=node,
                    description=node.get("description", ""),
                )
                assembled[name] = await field_value(child)
            return None if assembled and all(v is None for v in assembled.values()) else assembled
        return await field_value(field)

    async def field_value(target: TargetFieldSpec) -> Any:
        nonlocal part_count, total_bytes
        if target.field_type == "object" and contains_array(target.raw_schema):
            return await field(target)
        if not target.is_array:
            result = await pipeline._extract_bounded(
                key=f"{key}:scalar:{digest(target.path)}", **{**kwargs, "target_fields": [target]}
            )
            evidence.update(result.evidence_by_field)
            return result.data.get(target.name)
        collected: list[Any] = []
        found = False
        for source_index, source in enumerate(kwargs["unit_inputs"]):
            source_base = len(collected)
            cursor = ""
            source_offset = 0
            canonical_text = source[0].native_text or ""
            seen: set[str] = set()
            page_number = 0
            limit = config.extraction_page_items
            while True:
                if part_count >= config.max_extraction_parts:
                    raise DocumentLimitExceededError(
                        "Extraction part limit exceeded; saved parts remain available."
                    )
                scope = digest(f"{key}:{target.path}:{source_index}:{page_number}:{cursor}")
                while split := pipeline._result_repo.load_step(
                    job.job_id, f"split:{scope}:{limit}"
                ):
                    limit = split["limit"]
                request = {
                    "limit": limit,
                    "after": "" if source_offset else cursor,
                    "slice_sequence": page_number,
                    "owned_unit": source[0].unit.unit_id,
                    "source_text_start": source_offset,
                }
                paged_spec = kwargs["spec"].model_copy(update={"output_page": request})
                owned_source = (
                    replace(source[0], native_text=canonical_text[source_offset:]),
                    source[1],
                )
                try:
                    result = await pipeline._model_step(
                        job.job_id,
                        "extract-page:" + scope + f":{limit}",
                        ExtractionBatchResult,
                        partial(
                            pipeline._extraction_engine.extract_fields,
                            **{
                                **kwargs,
                                "spec": paged_spec,
                                "target_fields": [target],
                                "unit_inputs": [owned_source],
                            },
                        ),
                    )
                except ModelOutputLimitExceededError:
                    if limit <= 1:
                        raise ModelOutputLimitExceededError(
                            "A record cannot fit the output limit; saved parts are incomplete."
                        ) from None
                    previous_limit = limit
                    limit = max(1, limit // 2)
                    # Distinct limit keys preserve immutable checkpoints on repeated splits.
                    pipeline._result_repo.save_step(
                        job.job_id, f"split:{scope}:{previous_limit}", {"limit": limit}, None
                    )
                    continue
                values = result.data.get(target.name)
                if values is None:
                    values = []
                else:
                    found = True
                if not isinstance(values, list) or len(values) > limit:
                    raise ModelOutputLimitExceededError(
                        "Collection output exceeds the requested page size."
                    )
                previous_offset = source_offset
                positions = []
                if result.record_anchors and canonical_text:
                    if len(result.record_anchors) != len(values):
                        raise ModelOutputLimitExceededError("Record anchors do not match the page.")
                    for anchor in result.record_anchors:
                        matches = list(
                            re.finditer(re.escape(anchor["quote"]), canonical_text[source_offset:])
                        )
                        occurrence = anchor["occurrence"]
                        if occurrence < 0 or occurrence >= len(matches):
                            raise ModelOutputLimitExceededError(
                                "Record anchor is outside owned text."
                            )
                        positions.append(source_offset + matches[occurrence].start())
                    if positions != sorted(set(positions)):
                        raise ModelOutputLimitExceededError(
                            "Record anchors repeat or change source order."
                        )
                    if positions:
                        source_offset = positions[-1] + len(result.record_anchors[-1]["quote"])
                        cells = source[0].unit.metadata.get("cell_spans", [])
                        owned_cell = next(
                            (c for c in cells if c["start"] <= positions[-1] < c["end"]), None
                        )
                        if owned_cell:
                            row = re.search(r"\d+$", owned_cell["cell"]).group()
                            source_offset = max(
                                c["end"] + 1
                                for c in cells
                                if re.search(r"\d+$", c["cell"]).group() == row
                            )
                        else:
                            end_line = canonical_text.find("\n", source_offset)
                            if end_line >= 0:
                                source_offset = end_line + 1
                if result.has_more and (
                    not values
                    or not result.cursor
                    or (result.cursor in seen and source_offset <= previous_offset)
                ):
                    raise ModelOutputLimitExceededError(
                        "Collection continuation made no source progress."
                    )
                if result.cursor:
                    seen.add(result.cursor)
                base = len(collected)
                for path, sources in result.evidence_by_field.items():
                    # Containers cite the union of their real leaves. A model's
                    # summarized range quote is not a verbatim source citation.
                    item_kind = target.raw_schema.get("items", {}).get("type", "")
                    local_suffix = (
                        path[len(target.path) + 1 :] if path.startswith(target.path + "/") else ""
                    )
                    if path == target.path or (
                        local_suffix.isdigit() and item_kind in ("object", "array")
                    ):
                        continue
                    if path.startswith(target.path + "/"):
                        suffix = path[len(target.path) + 1 :]
                        index, separator, tail = suffix.partition("/")
                        if index.isdigit():
                            # A provider may label leaf evidence with source/global
                            # row indices. Resolve the record from its original-text
                            # anchor instead of guessing from equal item values.
                            resolved = set()
                            if positions:
                                for citation in sources:
                                    if citation.unit_id != source[0].unit.unit_id:
                                        continue
                                    for quote in (citation.quote, citation.raw_value):
                                        if not quote:
                                            continue
                                        matches = list(
                                            re.finditer(build_token_pattern(quote), canonical_text)
                                        )
                                        matches = [
                                            m
                                            for m in matches
                                            if m.start() == 0
                                            or not canonical_text[m.start() - 1].isalnum()
                                        ]
                                        if len(matches) == 1:
                                            point = matches[0].start()
                                            candidates = [
                                                i
                                                for i, start in enumerate(positions)
                                                if start
                                                <= point
                                                < (
                                                    positions[i + 1]
                                                    if i + 1 < len(positions)
                                                    else len(canonical_text)
                                                )
                                            ]
                                            resolved.update(candidates)
                                            break
                            if len(resolved) == 1:
                                index = str(resolved.pop())
                            path = f"{target.path}/{base + int(index)}" + (
                                "/" + tail if separator else ""
                            )
                    evidence.setdefault(path, []).extend(sources)
                if positions:
                    for index, item in enumerate(values):
                        start = positions[index]
                        end = positions[index + 1] if index + 1 < len(positions) else source_offset
                        cells = source[0].unit.metadata.get("cell_spans", [])
                        cell = next((c for c in cells if c["start"] <= start < c["end"]), None)
                        if cell:
                            row = re.search(r"\d+$", cell["cell"]).group()
                            end = min(
                                end,
                                max(
                                    c["end"]
                                    for c in cells
                                    if re.search(r"\d+$", c["cell"]).group() == row
                                ),
                            )
                        for pointer, scalar in scalar_leaves(item, f"{target.path}/{base + index}"):
                            if not evidence.get(pointer):
                                anchored = anchor_value(
                                    scalar, canonical_text, start, end, source[0].unit.unit_id
                                )
                                if anchored:
                                    evidence[pointer] = [anchored]
                # Advance over original text using a unique citation from the final
                # returned record. The next call cannot see earlier owned records.
                if values and canonical_text and not result.record_anchors:
                    last = f"{target.path}/{len(values) - 1}"
                    ends = []
                    for path, citations in result.evidence_by_field.items():
                        if path == last or path.startswith(last + "/"):
                            for citation in citations:
                                for quote in (citation.quote, citation.raw_value):
                                    if quote and canonical_text.count(quote) == 1:
                                        end = canonical_text.index(quote) + len(quote)
                                        if end > source_offset:
                                            ends.append(end)
                    if ends:
                        source_offset = max(ends)
                        if source[1].value == "TEXT" and not canonical_text[source_offset:].strip():
                            result.has_more = False
                collected.extend(values)
                total_bytes += len(json.dumps(asdict(result), default=str).encode())
                if total_bytes > config.max_result_bytes:
                    raise DocumentLimitExceededError("Extraction result-byte limit exceeded.")
                # A client may inspect these durable candidates during processing/failure.
                # They are explicitly provisional, never presented as independently verified.
                pipeline._result_repo.save_step(
                    job.job_id,
                    f"partial:{part_count:06d}:{scope}",
                    {
                        "path": target.path,
                        "start_index": base,
                        "items": values,
                        "source_unit": source[0].unit.unit_id,
                        "complete_scope": not result.has_more,
                        "verification": "pending",
                        "stage": kwargs["stage_name"],
                    },
                    None,
                )
                part_count += 1
                page_number += 1
                if not result.has_more:
                    break
                cursor = result.cursor
            count_target = TargetFieldSpec(
                path=target.path,
                name="owned_record_count",
                field_type="integer",
                raw_schema={"type": "integer"},
                description=(
                    f"Exact number of records for {target.path}: {target.description}. "
                    f"Count records STARTING in owned source unit {source[0].unit.unit_id}. "
                    "Exclude headings and adjacent context; include equal but distinct records."
                ),
            )
            if job.configuration.pipeline_mode.value == "decision_led":
                count = len(collected) - source_base
                checked = await pipeline._model_step(
                    job.job_id,
                    "source-count:" + digest(f"{key}:{target.path}:{source_index}"),
                    VerificationBatchResult,
                    partial(
                        pipeline._decision_engine.verify_fields,
                        job_id=job.job_id,
                        fields_to_verify=[(count_target, count, [])],
                        unit_payloads_by_id={source[0].unit.unit_id: source[0]},
                        model_id=config.decision_model,
                    ),
                )
                outcome = checked.outcomes[target.path]
                if outcome.status == VerificationStatus.CONTRADICTED and not recovering:
                    replacement = await extract_partitioned(
                        pipeline,
                        key=f"{key}:recover-source:{digest(target.path)}:{source_index}",
                        **{
                            **kwargs,
                            "target_fields": [target],
                            "unit_inputs": [source],
                            "stage_name": "recovering_collection",
                            "_recovering": True,
                            "spec": kwargs["spec"].model_copy(
                                update={
                                    "instructions": kwargs["spec"].instructions
                                    + "\nIndependent source counting found "
                                    "missing or duplicate records. Rescan this owned unit fully; "
                                    "start at its first record and do not summarize."
                                }
                            ),
                        },
                    )
                    collected[source_base:] = replacement.data.get(target.name) or []
                    for pointer in list(evidence):
                        if pointer.startswith(target.path + "/"):
                            segment = pointer[len(target.path) + 1 :].split("/", 1)[0]
                            if segment.isdigit() and int(segment) >= source_base:
                                del evidence[pointer]
                    for pointer, citations in replacement.evidence_by_field.items():
                        if pointer.startswith(target.path + "/"):
                            segment, sep, tail = pointer[len(target.path) + 1 :].partition("/")
                            if segment.isdigit():
                                pointer = f"{target.path}/{source_base + int(segment)}" + (
                                    "/" + tail if sep else ""
                                )
                        if pointer != target.path:
                            evidence.setdefault(pointer, []).extend(citations)
                    found = found or replacement.data.get(target.name) is not None
                pipeline._result_repo.save_step(
                    job.job_id,
                    "scope-count:" + digest(f"{key}:{target.path}:{source_index}"),
                    {
                        "path": target.path,
                        "source_unit": source[0].unit.unit_id,
                        "count": len(collected) - source_base,
                        "stage": kwargs["stage_name"],
                    },
                    None,
                )
        return collected if found else None

    for target in kwargs["target_fields"]:
        value = await field(target)
        data[target.name] = value
    for path in sorted(list(evidence), key=len, reverse=True):
        segments = path.split("/")
        for length in range(2, len(segments)):
            parent_path = "/".join(segments[:length])
            if not evidence.get(parent_path):
                evidence[parent_path] = [
                    s
                    for p, sources in list(evidence.items())
                    if p.startswith(parent_path + "/")
                    for s in sources
                ]
    # Container citations are derived only from real child citations, never from
    # search context. This lets callers retain provenance after object partitioning.
    for target in kwargs["target_fields"]:
        if not evidence.get(target.path):
            evidence[target.path] = [
                source
                for path, sources in list(evidence.items())
                if path.startswith(target.path + "/")
                for source in sources
            ]
    return ExtractionBatchResult(data=data, evidence_by_field=evidence, model_id=kwargs["model_id"])
