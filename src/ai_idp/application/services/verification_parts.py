"""Partition candidate values without treating an object wrapper as indivisible."""

import json
from typing import Any

from ai_idp.domain.errors import ModelInputLimitExceededError


def value_parts(value: Any, *, max_characters: int = 8000, max_items: int = 25) -> list[Any]:
    if len(json.dumps(value, ensure_ascii=True)) <= max_characters and not (
        isinstance(value, list) and len(value) > max_items
    ):
        return [value]
    if isinstance(value, list) and value:
        if len(value) > max_items:
            return [
                part
                for start in range(0, len(value), max_items)
                for part in value_parts(
                    value[start : start + max_items],
                    max_characters=max_characters,
                    max_items=max_items,
                )
            ]
        if len(value) == 1:
            return [[part] for part in value_parts(value[0], max_characters=max_characters - 2)]
        middle = max(1, len(value) // 2)
        return [
            *value_parts(value[:middle], max_characters=max_characters, max_items=max_items),
            *value_parts(value[middle:], max_characters=max_characters, max_items=max_items),
        ]
    if isinstance(value, dict) and value:
        return [
            {key: part}
            for key, child in value.items()
            for part in value_parts(
                child,
                max_characters=max_characters - len(json.dumps(key)) - 4,
                max_items=max_items,
            )
        ]
    raise ModelInputLimitExceededError("An indivisible verification value exceeds its limit.")
