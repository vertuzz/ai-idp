import hashlib
import json
from io import BytesIO

import pytest

from scripts import prepare_cord_preview as preview


def test_download_rejects_corrupted_cache_without_network(tmp_path, monkeypatch):
    cached = tmp_path / "source.parquet"
    cached.write_bytes(b"changed")

    def unexpected_network(*args, **kwargs):
        pytest.fail("A corrupted cache must fail locally")

    monkeypatch.setattr(preview, "urlopen", unexpected_network)
    with pytest.raises(ValueError, match="Cached asset"):
        preview.download("https://example.invalid", cached, "0" * 64, 7)


@pytest.mark.parametrize("payload", [b"short", b"too much data", b"wrong!"])
def test_download_never_publishes_invalid_bytes(tmp_path, monkeypatch, payload):
    destination = tmp_path / "source.parquet"
    monkeypatch.setattr(preview, "urlopen", lambda *a, **kw: BytesIO(payload))
    with pytest.raises(ValueError):
        preview.download("https://example.invalid", destination, "0" * 64, 6)
    assert not destination.exists()
    assert not destination.with_suffix(".parquet.part").exists()


def test_case_preserves_upstream_identity_and_requires_review(tmp_path):
    # The writer validates the signature; full image decoding is outside this unit test.
    image_bytes = b"\x89PNG\r\n\x1a\nfixture"
    labels = json.dumps({"meta": {"split": "train", "image_id": 42}, "gt_parse": {}})
    source = {
        "dataset": "fixture",
        "revision": "pinned",
        "shard": "train.parquet",
        "upstream_split": "train",
        "license": "fixture",
        "attribution": "fixture",
        "rights_status": "pending",
    }
    case = preview.save_case(
        {"ground_truth": labels, "image": {"bytes": image_bytes, "path": "../../unsafe"}},
        7,
        source,
        tmp_path,
    )
    assert case["case_id"] == "cord-v2-train-0042"
    assert case["sha256"] == hashlib.sha256(image_bytes).hexdigest()
    assert (tmp_path / case["upstream_annotation"]).read_text(encoding="utf-8") == labels
    assert case["suite_split"] is None
    assert case["evaluation_ready"] is False
    assert case["annotation_review"] == "pending"
