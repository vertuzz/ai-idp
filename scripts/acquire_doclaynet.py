"""Select real DocLayNet pages and retrieve individual ZIP members with HTTP ranges."""

import random
from pathlib import Path

import ijson
from remotezip import RemoteZip

from scripts.prepare_cord_preview import ROOT, sha256, write_json

BASE = "https://codait-cos-dax.s3.us.cloud-object-storage.appdomain.cloud/dax-doclaynet/1.0.0/"
CACHE = ROOT / "eval/cache/doclaynet"
OUTPUT = ROOT / "eval/downloads/corpus/doclaynet"


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    parents = set()
    rng = random.Random(1729)
    with (
        RemoteZip(
            BASE + "DocLayNet_core.zip", initial_buffer_size=16 * 1024**2, timeout=90
        ) as core,
        RemoteZip(
            BASE + "DocLayNet_extra.zip", initial_buffer_size=16 * 1024**2, timeout=90
        ) as extra,
    ):
        print("Opened official DocLayNet archives using byte ranges", flush=True)
        for upstream, split, count in [
            ("train", "development", 21),
            ("val", "calibration", 7),
            ("test", "holdout", 7),
        ]:
            metadata = CACHE / f"{upstream}.json"
            if not metadata.exists():
                print(f"Caching {upstream} layout metadata", flush=True)
                with core.open(f"COCO/{upstream}.json") as source, metadata.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
            with metadata.open("rb") as stream:
                images = [
                    x
                    for x in ijson.items(stream, "images.item")
                    if int(x.get("precedence", 0)) == 0
                ]
            categories = sorted({x["doc_category"] for x in images})
            pools = {}
            for category in categories:
                pool = sorted(
                    (x for x in images if x["doc_category"] == category),
                    key=lambda x: x["file_name"],
                )
                rng.shuffle(pool)
                pools[category] = pool
            selected = []
            while len(selected) < count:
                progress = False
                for category in categories:
                    while pools[category]:
                        image = pools[category].pop()
                        parent = image["doc_name"]
                        if parent not in parents:
                            parents.add(parent)
                            selected.append(image)
                            progress = True
                            break
                    if len(selected) == count:
                        break
                if not progress:
                    raise ValueError("Insufficient unique original documents")
            ids = {int(x["id"]) for x in selected}
            annotations = {image_id: [] for image_id in ids}
            with metadata.open("rb") as stream:
                for annotation in ijson.items(stream, "annotations.item", use_float=True):
                    image_id = int(annotation["image_id"])
                    if image_id in ids:
                        annotations[image_id].append(annotation)
            for image in selected:
                stem = Path(image["file_name"]).stem
                case_id = f"doclaynet-{stem}"
                assets = {}
                for suffix, archive, member in [
                    ("pdf", extra, f"PDF/{stem}.pdf"),
                    ("json", extra, f"JSON/{stem}.json"),
                    ("png", core, f"PNG/{stem}.png"),
                ]:
                    target = OUTPUT / f"{stem}.{suffix}"
                    if not target.exists():
                        target.write_bytes(archive.read(member))
                    info = archive.getinfo(member)
                    assets[suffix] = {
                        "path": target.relative_to(ROOT).as_posix(),
                        "sha256": sha256(target),
                        "archive_member": member,
                        "zip_crc32": f"{info.CRC:08x}",
                        "bytes": target.stat().st_size,
                    }
                upstream_path = OUTPUT / f"{stem}.layout.json"
                write_json(
                    upstream_path, {"image": image, "annotations": annotations[int(image["id"])]}
                )
                record = {
                    "case_id": case_id,
                    "source": "doclaynet",
                    "format": "pdf",
                    "split": split,
                    "upstream_split": upstream,
                    "group_id": "doclaynet-parent:" + image["doc_name"],
                    "original_page": image["page_no"],
                    "category": image["doc_category"],
                    "source_url": BASE + "DocLayNet_extra.zip",
                    "source_revision": "1.0.0",
                    "assets": assets,
                    "path": assets["pdf"]["path"],
                    "sha256": assets["pdf"]["sha256"],
                    "upstream_annotation": upstream_path.relative_to(ROOT).as_posix(),
                    "license": "CDLA-Permissive-1.0",
                    "license_url": "https://cdla.dev/permissive-1-0/",
                    "attribution": "DocLayNet, IBM Research / Auer et al.; dataset release 1.0.0.",
                    "rights_status": (
                        "dataset_license_checked; embedded_third_party_rights_review_pending"
                    ),
                    "status": "downloaded",
                    "evaluation_ready": False,
                    "tags": [image["doc_category"], "single_page", "native_pdf"],
                }
                records.append(record)
                write_json(CACHE / "inventory.json", records)
                print(
                    f"DocLayNet {len(records)}/35: {image['doc_category']} {image['doc_name']}",
                    flush=True,
                )
    write_json(ROOT / "eval/doclaynet-selection.json", records)


if __name__ == "__main__":
    main()
