"""Mechanical scalar anchoring inside model-selected original record spans only."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from ai_idp.domain.field_paths import escape_segment
from ai_idp.domain.models import Evidence, TextSpan
from ai_idp.domain.validation import build_token_pattern


def scalar_leaves(value: Any, path: str):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from scalar_leaves(child, path + "/" + escape_segment(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from scalar_leaves(child, path + f"/{index}")
    elif value is not None and value != "":
        yield path, value


def anchor_value(value: Any, text: str, start: int, end: int, unit_id: str) -> Evidence | None:
    region = text[start:end]
    if isinstance(value, bool):
        matches = list(re.finditer(r"\b" + str(value) + r"\b", region, re.I))
    elif isinstance(value, (int, float)):
        matches = []
        for match in re.finditer(
            r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?%?(?!\w)", region
        ):
            try:
                if Decimal(match.group().rstrip("%").replace(",", "")) == Decimal(str(value)):
                    matches.append(match)
            except InvalidOperation:
                pass
    else:
        matches = list(re.finditer(build_token_pattern(str(value)), region))
    if len(matches) != 1:
        return None
    match = matches[0]
    absolute_start, absolute_end = start + match.start(), start + match.end()
    quote = text[absolute_start:absolute_end]
    return Evidence(
        unit_id=unit_id,
        quote=quote,
        raw_value=quote,
        locator={"anchor_method": "unique_value_in_model_cited_record"},
        text_span=TextSpan(
            start=absolute_start,
            end=absolute_end,
            text=quote,
            artifact_ref=unit_id,
            artifact_sha256=hashlib.sha256(text.encode()).hexdigest(),
        ),
    )
