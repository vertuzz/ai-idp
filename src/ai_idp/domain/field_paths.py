"""JSON Pointer handling and concrete leaf targets for partial extraction results."""

from __future__ import annotations

import copy
from typing import Any

from ai_idp.domain.models import TargetFieldSpec


def escape_segment(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def pointer_parts(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError("A JSON Pointer must start with '/'.")
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]


def get_pointer(data: Any, pointer: str) -> tuple[bool, Any]:
    current = data
    for part in pointer_parts(pointer):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def set_pointer(data: dict[str, Any], pointer: str, value: Any) -> None:
    parts = pointer_parts(pointer)
    if not parts:
        raise ValueError("Cannot replace the extraction root.")
    current: Any = data
    for idx, part in enumerate(parts):
        last = idx == len(parts) - 1
        if isinstance(current, list):
            pos = int(part)
            while len(current) <= pos:
                current.append(None)
            if last:
                current[pos] = copy.deepcopy(value)
                return
            if current[pos] is None:
                current[pos] = [] if parts[idx + 1].isdigit() else {}
            current = current[pos]
        else:
            if last:
                current[part] = copy.deepcopy(value)
                return
            if not isinstance(current.get(part), (dict, list)):
                current[part] = [] if parts[idx + 1].isdigit() else {}
            current = current[part]


def concrete_targets(
    schema: dict[str, Any], data: dict[str, Any], *, max_fields: int = 2000
) -> list[TargetFieldSpec]:
    """Keep containers for completeness checks and independently verify every leaf.

    Containers retain their original shape for lossless reconstruction. Missing required
    children are explicit null candidates, never invented values. A nullable absent
    container is checked as an absence claim instead of manufacturing its children.
    """
    from ai_idp.domain.errors import DocumentLimitExceededError

    targets: list[TargetFieldSpec] = []

    def visit(node: dict[str, Any], value: Any, path: str, required: bool) -> None:
        types = node.get("type", "string")
        type_list = types if isinstance(types, list) else [types]
        primary = next((t for t in type_list if t != "null"), "null")
        nullable = "null" in type_list or not required
        name = pointer_parts(path)[0] if len(pointer_parts(path)) == 1 else path
        targets.append(
            TargetFieldSpec(
                path=path,
                name=name,
                field_type=primary,
                description=node.get("description", ""),
                required=required,
                nullable=nullable,
                is_array=primary == "array",
                raw_schema=node,
            )
        )
        if len(targets) > max_fields:
            raise DocumentLimitExceededError("Extracted field count exceeds the configured limit.")
        if value is None and nullable:
            return
        if primary == "object":
            required_names = set(node.get("required", []))
            for key, child in node.get("properties", {}).items():
                child_value = value.get(key) if isinstance(value, dict) else None
                visit(child, child_value, path + "/" + escape_segment(key), key in required_names)
        elif primary == "array" and isinstance(value, list):
            for idx, item in enumerate(value):
                visit(node["items"], item, path + f"/{idx}", True)

    required = set(schema.get("required", []))
    for key, node in schema["properties"].items():
        visit(node, data.get(key), "/" + escape_segment(key), key in required)
    return targets


def assemble_fields(fields: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for path, field in sorted(fields.items(), key=lambda item: len(pointer_parts(item[0]))):
        set_pointer(data, path, field.value)
    return data
