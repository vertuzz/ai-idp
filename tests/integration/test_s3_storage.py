import boto3
import pymupdf
import pytest
from moto import mock_aws

from ai_idp.adapters.inbound.http.dependencies import build_blob_store, build_container
from ai_idp.adapters.outbound.storage.s3 import S3DocumentBlobStore
from ai_idp.domain.errors import DomainError
from ai_idp.settings import Settings

BUCKET = "parsefox-test"


@pytest.fixture
def s3(monkeypatch):
    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",  # pragma: allowlist secret -- moto placeholder
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def node(tmp_path, name: str) -> Settings:
    """One API/worker node: shared database and bucket, its own local cache."""
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path.as_posix()}/core.db",
        local_storage_root=tmp_path / name,
        local_telemetry_root=tmp_path / f"{name}-traces",
        storage_backend="s3",
        s3_bucket=BUCKET,
        s3_prefix="documents",
    )


def test_blobs_written_on_one_node_are_readable_on_another(tmp_path, s3):
    first = build_blob_store(node(tmp_path, "a"))
    second = build_blob_store(node(tmp_path, "b"))
    assert isinstance(first, S3DocumentBlobStore)
    first.put_text("doc_1/text.txt", "Invoice INV-7")
    assert s3.get_object(Bucket=BUCKET, Key="documents/doc_1/text.txt")["Body"].read() == (
        b"Invoice INV-7"
    )
    assert second.exists("doc_1/text.txt")
    assert second.get_text("doc_1/text.txt") == "Invoice INV-7"
    assert second.get_size("doc_1/text.txt") == 13
    assert (tmp_path / "b" / "doc_1" / "text.txt").is_file()
    assert first.check_health() and second.check_health()

    second.delete("doc_1/text.txt")
    assert not first.exists("doc_1/missing.txt")
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET, Prefix="documents/doc_1/text")
    with pytest.raises(DomainError):
        second.get_bytes("doc_1/text.txt")
    with pytest.raises(DomainError):
        first.put_bytes("../escape", b"x")


def test_pdf_pages_render_on_a_node_that_did_not_ingest_the_document(tmp_path, s3):
    ingesting = build_container(node(tmp_path, "a"), create_tables=True)
    pdf = pymupdf.open()
    for i in range(3):
        pdf.new_page().insert_text((40, 60), f"SYNTHETIC PAGE {i + 1}")
    document = ingesting.ingest_use_case.execute(raw_bytes=pdf.tobytes(), filename="three.pdf")
    pdf.close()
    keys = [item["Key"] for item in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert any(key.endswith(".render.json") for key in keys)
    assert not any(key.endswith(".png") for key in keys)

    serving = build_container(node(tmp_path, "b"))
    unit = serving.job_repo.get_units(document.document_id)[1]
    image = serving.blob_store.get_bytes(unit.image_ref)
    assert image.startswith(b"\x89PNG")
    # Rendered pages stay in the local cache; the bucket holds originals and descriptors.
    keys = [item["Key"] for item in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert not any(key.endswith(".png") for key in keys)
    assert list((tmp_path / "b").rglob("*.png"))


def test_unhealthy_when_the_bucket_is_missing(tmp_path, s3):
    store = S3DocumentBlobStore(
        build_blob_store(Settings(_env_file=None, local_storage_root=tmp_path / "c")),
        "missing-bucket",
        client=s3,
    )
    assert not store.check_health()
