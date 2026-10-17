"""Acquire 30 CORD receipts, preserving official train/validation/test distinctions."""

import json
from pathlib import Path

import pyarrow.parquet as parquet

from scripts.prepare_cord_preview import ROOT, download, save_case, write_json


def main():
    source = json.loads((ROOT / "eval/cord-preview-source.json").read_text(encoding="utf-8"))
    selections = [
        (
            "train",
            "development",
            source["shard"],
            source["shard_bytes"],
            source["shard_sha256"],
            [0, 11, 21, 31, 42, 52, 62, 73, 83, 93, 103, 113, 124, 135, 146, 157, 171, 190],
        ),
        (
            "validation",
            "calibration",
            "data/validation-00000-of-00001-cc3c5779fe22e8ca.parquet",
            242080800,
            # pragma: allowlist nextline secret (public upstream shard checksum)
            "0d0f6dac11fdcc549de2746aa9f53136a3bc22a2a1aff2b0b847f7622ad60c15",
            [15, 34, 51, 55, 68, 80],
        ),
        (
            "test",
            "holdout",
            "data/test-00000-of-00001-9c204eb3f4e11791.parquet",
            234202795,
            # pragma: allowlist nextline secret (public upstream shard checksum)
            "51c65f1788faff392abe2a0b55b023eb23e9be551c509138eaa3a832514224e7",
            [4, 15, 19, 36, 53, 87],
        ),
    ]
    output = ROOT / "eval/downloads/corpus/cord_v2"
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for upstream, split, shard, size, digest, indices in selections:
        annotation_split = "valid" if upstream == "validation" else upstream
        config = dict(source, upstream_split=annotation_split, shard=shard)
        url = f"https://huggingface.co/datasets/{source['dataset']}/resolve/{source['revision']}/{shard}"
        cache = ROOT / "eval/cache" / source["revision"] / Path(shard).name
        print(f"Fetching/verifying CORD {upstream} shard", flush=True)
        download(url, cache, digest, size)
        with parquet.ParquetFile(cache) as data:
            for index, batch in enumerate(data.iter_batches(batch_size=1)):
                if index in indices:
                    case = save_case(batch.to_pylist()[0], index, config, output)
                    case.update(
                        {
                            "source": "cord_v2",
                            "format": "png",
                            "split": split,
                            "annotation_split": annotation_split,
                            "upstream_split": upstream,
                            "source_url": url,
                            "source_revision": source["revision"],
                            "path": (output / case["image"]).relative_to(ROOT).as_posix(),
                            "upstream_annotation": (output / case["upstream_annotation"])
                            .relative_to(ROOT)
                            .as_posix(),
                            "group_id": f"cord-receipt:{upstream}:{case['upstream_image_id']}",
                            "tags": ["receipt", "image", "line_items"],
                            "license_url": source["license_url"],
                        }
                    )
                    case.pop("suite_split")
                    if upstream == "train" and index in {103, 124}:
                        case["group_id"] = "cord-layout-family:blue-banquet-receipt"
                    case["group_review"] = (
                        "preliminary_visual_selection; human_adjudication_pending"
                    )
                    records.append(case)
                if index >= max(indices):
                    break
        write_json(ROOT / "eval/cache/cord-inventory.json", records)
        print(f"CORD: {len(records)}/30 acquired", flush=True)
    write_json(ROOT / "eval/cord-selection.json", records)


if __name__ == "__main__":
    main()
