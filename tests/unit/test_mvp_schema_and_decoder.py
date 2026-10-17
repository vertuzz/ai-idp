from pathlib import Path

import jsonschema
import pytest

from ai_idp.adapters.outbound.documents.isolated_reader import IsolatedDocumentReader
from ai_idp.adapters.outbound.openrouter.extraction_client import build_extraction_envelope_schema
from ai_idp.adapters.outbound.storage.local import LocalDocumentBlobStore
from ai_idp.domain.errors import DocumentLimitExceededError, InvalidSchemaError
from ai_idp.domain.field_paths import concrete_targets, get_pointer, set_pointer
from ai_idp.domain.models import Document
from ai_idp.domain.schema_normalizer import normalize_extraction_schema
from ai_idp.settings import Settings


def test_nested_partial_schema_and_escaped_json_pointers():
    schema = {
        "type": "object",
        "properties": {
            "a/b": {"type": "object", "properties": {"~x": {"type": "string"}}, "required": ["~x"]}
        },
        "required": ["a/b"],
    }
    spec = normalize_extraction_schema(schema)
    jsonschema.validate(
        {"a/b": {"~x": None}, "_evidence": []}, build_extraction_envelope_schema(spec.fields)
    )
    fields = concrete_targets(schema, {"a/b": {"~x": None}})
    assert fields[-1].path == "/a~1b/~0x"
    data = {"a/b": {}}
    set_pointer(data, "/a~1b/~0x", "correct")
    assert get_pointer(data, "/a~1b/~0x") == (True, "correct")


def test_optional_absence_is_omitted_while_required_unknowns_remain_visible():
    from ai_idp.domain.partial_data import project_partial_data

    data = {"optional": None, "required": None, "nullable": None}
    schema = {
        "type": "object",
        "properties": {
            "optional": {"type": "string"},
            "required": {"type": "string"},
            "nullable": {"type": ["string", "null"]},
        },
        "required": ["required"],
    }
    assert project_partial_data(data, schema) == {"required": None, "nullable": None}
    assert "optional" in data


@pytest.mark.parametrize(
    "property_schema",
    [
        {"anyOf": [{"$ref": "https://example.invalid/schema"}]},
        {"type": ["string", "number"]},
        {"type": "array"},
    ],
)
def test_unsupported_schemas_fail_before_model_work(property_schema):
    with pytest.raises(InvalidSchemaError):
        normalize_extraction_schema({"type": "object", "properties": {"field": property_schema}})


@pytest.mark.parametrize(
    "limits", [{"document_timeout_seconds": 0.001}, {"document_memory_mib": 1}]
)
def test_decoder_is_killed_on_resource_limit_without_publishing_artifacts(tmp_path, limits):
    reader = IsolatedDocumentReader(Settings(**limits))
    store = LocalDocumentBlobStore(tmp_path)
    path = Path(__file__).resolve().parents[2] / "eval/fixtures/synthetic/synthetic-native-01.pdf"
    document = Document(
        document_id="limited",
        filename=path.name,
        media_type="application/pdf",
        sha256="unused",
        bytes_size=path.stat().st_size,
        storage_key="input",
    )
    with pytest.raises(DocumentLimitExceededError):
        reader.normalize(document, path.read_bytes(), store)
    assert not list(tmp_path.rglob("*.png"))
