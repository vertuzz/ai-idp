"""Render local PDF previews and contact sheets; originals remain untouched."""

import json
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageOps

from scripts.prepare_cord_preview import ROOT


def contact_sheet(entries, target, columns=5, width=280, height=390):
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, rows * height), "#e4e7eb")
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(entries):
        with Image.open(path) as original:
            thumb = ImageOps.contain(original.convert("RGB"), (width - 16, height - 38))
        x, y = (index % columns) * width, (index // columns) * height
        sheet.paste(thumb, (x + (width - thumb.width) // 2, y + 25))
        draw.text((x + 7, y + 6), label[:42], fill="black")
    sheet.save(target)


def main():
    poppler = shutil.which("pdftoppm")
    if not poppler:
        raise RuntimeError("PDF preview preparation requires Poppler pdftoppm")
    cases = [
        json.loads(line)
        for line in (ROOT / "eval/manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    output = ROOT / "eval/cache/visual-qa"
    output.mkdir(parents=True, exist_ok=True)
    synthetic = []
    for case in cases:
        if case["source"] == "synthetic" and case["format"] == "docx":
            folder = ROOT / "eval/cache/docx-qa" / case["case_id"]
            synthetic.extend(
                (case["case_id"] + " " + p.stem, p) for p in sorted(folder.glob("page-*.png"))
            )
        elif case["source"] == "synthetic":
            prefix = output / case["case_id"]
            subprocess.run(
                [poppler, "-scale-to", "1400", "-png", str(ROOT / case["path"]), str(prefix)],
                check=True,
                capture_output=True,
            )
            synthetic.extend((p.stem, p) for p in sorted(output.glob(case["case_id"] + "-*.png")))
    for offset in range(0, len(synthetic), 15):
        target = output / f"synthetic-sheet-{offset // 15 + 1}.png"
        contact_sheet(synthetic[offset : offset + 15], target)
        print(target)
    for source in ["cord_v2", "doclaynet"]:
        images = []
        for case in cases:
            if case["source"] == source:
                path = case["assets"]["png"]["path"] if source == "doclaynet" else case["path"]
                label = (
                    case.get("category", "receipt")
                    + " "
                    + case["split"]
                    + " "
                    + case["case_id"][-8:]
                )
                images.append((label, ROOT / path))
        for offset in range(0, len(images), 15):
            contact_sheet(
                images[offset : offset + 15], output / f"{source}-sheet-{offset // 15 + 1}.png"
            )


if __name__ == "__main__":
    main()
