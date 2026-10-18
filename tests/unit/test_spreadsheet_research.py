"""Research tooling must preserve source identities and distinguish cached blanks."""

import hashlib
import json
import zipfile

import pytest

from scripts import research_spreadsheets as research


def test_cached_empty_string_is_not_missing_formula_result(tmp_path):
    path = tmp_path / "package.bin"
    prefix = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", f"<workbook {prefix}><sheets/></workbook>")
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f"<worksheet {prefix}><sheetData><row>"
            '<c r="A1" t="str"><f>IF(1=1,"",1)</f><v/></c>'
            '<c r="B1"><f>1+1</f><v>2</v></c>'
            '<c r="C1"><f>1+1</f></c>'
            '<c r="D1"><f>1+1</f><v/></c>'
            "</row></sheetData></worksheet>",
        )
    info = research.inspect_ooxml(path)
    assert info["formulas"] == 4
    assert info["formulas_with_empty_string_cache"] == 1
    assert info["formulas_without_cached_value"] == 2


def test_changed_research_source_is_preserved(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "filename": "source.bin",
                        "sha256": hashlib.sha256(b"original").hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.bin"
    source.write_bytes(b"changed locally")
    monkeypatch.setattr(research, "CATALOG", catalog)
    monkeypatch.setattr(research, "DOWNLOADS", tmp_path)
    with pytest.raises(ValueError, match="Source changed"):
        research.verified_sources()
    assert source.read_bytes() == b"changed locally"


def test_encrypted_container_is_reported_without_zip_crash(tmp_path):
    path = tmp_path / "encrypted.bin"
    path.write_bytes(bytes.fromhex("d0cf11e0a1b11ae1"))
    assert "not-zip" in research.inspect_ooxml(path)["status"]
