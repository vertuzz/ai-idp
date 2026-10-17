import io
import json
import zipfile

import pytest

from scripts.check_repository import check_blob


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "eval/results/output.json",
        "eval/downloads/input.pdf",
        "data/raw.txt",
        "private.key",
        "model-output.jsonl",
    ],
)
def test_local_and_sensitive_artifacts_cannot_be_published(path):
    assert check_blob(path, b"{}")


def test_personal_paths_are_reported_without_echoing_their_content():
    private = "C:" + "/Users/" + "private-person/file.txt"
    errors = check_blob("docs/example.md", private.encode())
    assert errors == ["personal local filesystem path"]
    assert all("private-person" not in error for error in errors)


@pytest.mark.parametrize(
    "path,data", [("bad.json", b"{"), ("bad.yaml", b"[:"), ("bad.toml", b"=x")]
)
def test_invalid_configs_fail_static_checks(path, data):
    assert check_blob(path, data) == ["invalid JSON, TOML or YAML"]


def test_document_metadata_requires_a_project_owned_identity():
    def document(author):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "docProps/core.xml",
                f'<core xmlns:dc="urn:dc"><dc:creator>{author}</dc:creator></core>',
            )
        return output.getvalue()

    path = "eval/fixtures/synthetic/test.docx"
    assert check_blob(path, document("AI-IDP")) == []
    assert check_blob(path, document("Private Author")) == [
        "document author/creator metadata needs review"
    ]


def test_env_example_and_binary_fixture_are_handled_explicitly():
    assert check_blob(".env.example", b"OPENROUTER_API_KEY=\n") == []
    assert check_blob("eval/fixtures/synthetic/test.png", b"\x89PNG\x00") == []


def test_secret_filter_only_accepts_actual_corpus_hash_fields():
    from scripts.secret_filters import is_public_corpus_hash

    digest = "a" * 64
    other = "b" * 64
    line = json.dumps({"sha256": digest, "api_key": other})
    assert is_public_corpus_hash(digest, "eval/manifest.jsonl", line)
    assert not is_public_corpus_hash(other, "eval/manifest.jsonl", line)
    assert not is_public_corpus_hash(digest, "settings.json", line)
