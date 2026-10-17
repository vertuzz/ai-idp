from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import jsonschema

from ai_idp.domain.errors import InvalidSchemaError
from ai_idp.domain.models import ExtractionSpecification, TargetFieldSpec

UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {"$ref", "$dynamicRef", "oneOf", "not", "patternProperties"}
)
MAX_SCHEMA_DEPTH = 6
MAX_SCHEMA_PROPERTIES = 100


def _check_schema_node(node: Any, depth: int = 0) -> None:
    if depth > MAX_SCHEMA_DEPTH:
        raise InvalidSchemaError(f"JSON Schema exceeds maximum nesting depth ({MAX_SCHEMA_DEPTH}).")
    if not isinstance(node, dict):
        return
    for kw in UNSUPPORTED_SCHEMA_KEYWORDS:
        if kw in node:
            raise InvalidSchemaError(f"Unsupported JSON Schema keyword: '{kw}'.")
    props = node.get("properties")
    if isinstance(props, dict):
        if len(props) > MAX_SCHEMA_PROPERTIES:
            raise InvalidSchemaError(
                f"JSON Schema object exceeds maximum property count ({MAX_SCHEMA_PROPERTIES})."
            )
        for sub in props.values():
            _check_schema_node(sub, depth + 1)
    items = node.get("items")
    if isinstance(items, dict):
        _check_schema_node(items, depth + 1)


def _resolve_type_info(prop_schema: dict[str, Any]) -> tuple[str, bool, bool]:
    raw_type = prop_schema.get("type", "string")
    nullable = False
    if isinstance(raw_type, list):
        non_null = [t for t in raw_type if t != "null"]
        nullable = "null" in raw_type
        primary_type = str(non_null[0]) if non_null else "string"
    else:
        primary_type = str(raw_type)
    if prop_schema.get("nullable") is True:
        nullable = True
    is_array = primary_type == "array"
    return primary_type, nullable, is_array


def normalize_extraction_schema(
    schema_json: dict[str, Any],
    instructions: str = "",
    spec_id: str | None = None,
) -> ExtractionSpecification:
    """Validate a caller JSON Schema and normalize it into TargetFieldSpec entries."""
    if not isinstance(schema_json, dict):
        raise InvalidSchemaError("Schema must be a JSON object.")

    try:
        jsonschema.Draft202012Validator.check_schema(schema_json)
    except jsonschema.SchemaError as exc:
        raise InvalidSchemaError(f"Invalid JSON Schema: {exc.message}") from exc

    root_type = schema_json.get("type")
    if root_type != "object":
        raise InvalidSchemaError("Root JSON Schema must have type 'object'.")

    properties = schema_json.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise InvalidSchemaError("Root JSON Schema must define a non-empty 'properties' object.")

    _check_schema_node(schema_json, depth=0)

    required_set = set(schema_json.get("required") or [])
    fields: list[TargetFieldSpec] = []

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            raise InvalidSchemaError(f"Property '{prop_name}' schema must be a JSON object.")
        field_type, nullable, is_array = _resolve_type_info(prop_schema)
        description = str(prop_schema.get("description") or "")
        if is_array and isinstance(prop_schema.get("items"), dict):
            item_props = prop_schema["items"].get("properties")
            if isinstance(item_props, dict) and item_props:
                item_names = ", ".join(item_props.keys())
                if description:
                    description = f"{description} (Array item fields: {item_names})"
                else:
                    description = f"Array of objects with fields: {item_names}"
        fields.append(
            TargetFieldSpec(
                path=f"/{prop_name}",
                name=prop_name,
                field_type=field_type,
                description=description,
                required=prop_name in required_set,
                nullable=nullable or (prop_name not in required_set),
                is_array=is_array,
                raw_schema=prop_schema,
            )
        )

    canonical_payload = json.dumps(
        {"schema": schema_json, "instructions": instructions.strip()},
        sort_keys=True,
        separators=(",", ":"),
    )
    schema_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    return ExtractionSpecification(
        spec_id=spec_id or f"spec_{uuid.uuid4().hex[:12]}",
        schema_json=schema_json,
        schema_hash=schema_hash,
        instructions=instructions.strip(),
        fields=fields,
    )


def validate_data_against_schema(
    data: dict[str, Any], schema_json: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Validate extracted data dictionary against the caller's JSON Schema."""
    validator = jsonschema.Draft202012Validator(schema_json)
    errors = [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in validator.iter_errors(data)
    ]
    return len(errors) == 0, errors
