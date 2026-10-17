"""Project internal absence candidates into the caller's optional-property semantics."""

from __future__ import annotations

import copy
from typing import Any


def project_partial_data(data: Any, schema: dict[str, Any]) -> Any:
    if isinstance(data, dict):
        result = copy.deepcopy(data)
        required = set(schema.get("required", []))
        for key, child in schema.get("properties", {}).items():
            if key not in result:
                continue
            types = child.get("type")
            nullable = types == "null" or isinstance(types, list) and "null" in types
            if result[key] is None and key not in required and not nullable:
                del result[key]
            else:
                result[key] = project_partial_data(result[key], child)
        return result
    if isinstance(data, list):
        return [project_partial_data(value, schema.get("items", {})) for value in data]
    return data
