"""Bounded, reusable schema proposals, separate from extracted document values."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_idp.domain.errors import InvalidSchemaError
from ai_idp.domain.models import UsageSummary
from ai_idp.domain.schema_normalizer import normalize_extraction_schema


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    unit_id: str


class SuggestedField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    kind: Literal["string", "number", "integer", "boolean", "object", "array"]
    fields: list[SuggestedField] = Field(default_factory=list, max_length=10)
    sources: list[SourceReference] = Field(default_factory=list, max_length=15)


class SchemaProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    fields: list[SuggestedField] = Field(min_length=1, max_length=10)


INSTRUCTIONS = (
    "Extract only information supported by the document. Use null for missing or unknown "
    "values. Preserve identifiers, leading zeros and source row associations. Copy dates as "
    "printed without guessing ambiguous formats. Do not calculate values that are not printed."
)


def compile_proposal(
    proposal: SchemaProposal, allowed_sources: set[tuple[str, str]]
) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    """Compile a restricted field plan; never copy arbitrary model JSON Schema keywords."""
    leaves = 0
    evidence: dict[str, list[dict[str, str]]] = {}

    def group(fields: list[SuggestedField], path: str, depth: int) -> dict[str, Any]:
        nonlocal leaves
        if depth > 2 or not fields or len({f.key for f in fields}) != len(fields):
            raise InvalidSchemaError("Suggested schema has invalid groups or duplicate keys.")
        properties = {}
        for field in fields:
            pointer = f"{path}/{field.key}"
            node: dict[str, Any] = {
                "type": [field.kind, "null"],
                "title": field.title,
                "description": field.description,
            }
            if field.kind in {"object", "array"}:
                child = group(
                    field.fields, pointer + ("/*" if field.kind == "array" else ""), depth + 1
                )
                if field.kind == "array":
                    node["items"] = child
                else:
                    node.update({k: v for k, v in child.items() if k != "type"})
            else:
                leaves += 1
                if field.fields or not field.sources:
                    raise InvalidSchemaError("Each suggested leaf needs source references.")
                if any((s.document_id, s.unit_id) not in allowed_sources for s in field.sources):
                    raise InvalidSchemaError("Suggested field cites an unavailable source.")
                evidence[pointer] = [s.model_dump() for s in field.sources]
            properties[field.key] = node
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    schema = {"title": proposal.name, **group(proposal.fields, "", 0)}
    if leaves > 20:
        raise InvalidSchemaError("Suggested schema exceeds 20 leaf fields.")
    normalize_extraction_schema(schema, instructions=INSTRUCTIONS)
    return schema, evidence


class SuggestionJob(BaseModel):
    job_id: str
    document_ids: list[str]
    status: str = "queued"
    stage: str = "queued"
    config: dict[str, Any] = Field(default_factory=dict)
    checkpoints: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    usage: UsageSummary = Field(default_factory=UsageSummary)
    attempts: int = 0
    execution_active: bool = False
    last_error: str | None = None


TERMINAL_SUGGESTION_STATUSES = {"completed", "needs_review", "failed", "cancelled"}
