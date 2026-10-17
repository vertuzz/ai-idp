"""Retrieve a pinned CORD starter sample; never promote upstream labels to reviewed gold."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url: str, destination: Path, expected_hash: str, expected_bytes: int) -> None:
    """Reuse verified cache entries and publish downloads only after integrity checks."""
    if destination.exists():
        if destination.stat().st_size != expected_bytes or sha256(destination) != expected_hash:
            raise ValueError(f"Cached asset failed integrity check: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            received = 0
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > expected_bytes:
                    raise ValueError("Download exceeded the pinned asset size")
                output.write(chunk)
        if received != expected_bytes or sha256(temporary) != expected_hash:
            raise ValueError("Downloaded asset failed integrity check")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_case(row: dict, index: int, source: dict, output: Path) -> dict:
    annotation = json.loads(row["ground_truth"])
    metadata = annotation["meta"]
    if metadata["split"] != source["upstream_split"]:
        raise ValueError("Annotation split disagrees with the pinned source")
    image_id = metadata["image_id"]
    if type(image_id) is not int or image_id < 0:
        raise ValueError("Expected a nonnegative upstream image ID")
    case_id = f"cord-v2-{metadata['split']}-{image_id:04d}"
    image_bytes = row["image"]["bytes"]
    if not image_bytes or not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Expected embedded PNG bytes from the pinned shard")
    image_path = output / f"{case_id}.png"
    label_path = output / f"{case_id}.upstream.json"
    image_path.write_bytes(image_bytes)
    # Preserve the upstream JSON string without remapping fields or normalizing amounts.
    label_path.write_text(row["ground_truth"], encoding="utf-8")
    return {
        "case_id": case_id,
        "dataset": source["dataset"],
        "revision": source["revision"],
        "shard": source["shard"],
        "row_index_in_shard": index,
        "upstream_split": metadata["split"],
        "upstream_image_id": image_id,
        "image": image_path.name,
        "sha256": sha256(image_path),
        "upstream_annotation": label_path.name,
        "annotation_sha256": sha256(label_path),
        "license": source["license"],
        "attribution": source["attribution"],
        "rights_status": source["rights_status"],
        "status": "downloaded",
        "suite_split": None,
        "group_review": "pending",
        "annotation_review": "pending",
        "evaluation_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "eval/downloads/cord-v2-preview")
    args = parser.parse_args()
    source = json.loads((ROOT / "eval/cord-preview-source.json").read_text(encoding="utf-8"))
    url = (
        f"https://huggingface.co/datasets/{source['dataset']}/resolve/"
        f"{source['revision']}/{source['shard']}"
    )
    cache = ROOT / "eval/cache" / source["revision"] / Path(source["shard"]).name
    print(f"Preparing five CORD train samples; pinned shard cache: {source['shard_bytes']:,} bytes")
    download(url, cache, source["shard_sha256"], source["shard_bytes"])

    import pyarrow.parquet as parquet

    args.output.mkdir(parents=True, exist_ok=True)
    wanted = set(source["row_indices"])
    cases = []
    with parquet.ParquetFile(cache) as shard:
        for index, batch in enumerate(shard.iter_batches(batch_size=1)):
            if index in wanted:
                cases.append(save_case(batch.to_pylist()[0], index, source, args.output))
            if index >= max(wanted):
                break
    if len(cases) != len(wanted):
        raise ValueError("Pinned source did not contain all requested rows")
    write_json(
        args.output / "inventory.json",
        {
            "status": "exploratory_unreviewed",
            "downloaded_at": datetime.now(UTC).isoformat(),
            "source_url": url,
            "cases": cases,
        },
    )
    print(f"Prepared {len(cases)} cases at {args.output}; field/evidence review is pending.")


if __name__ == "__main__":
    main()
