import io
import json
from decimal import Decimal
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from ai_idp.adapters.outbound.documents.formulas import (
    FormulaCell,
    FormulaEvaluator,
    UnsupportedFormula,
)
from tests.unit.test_spreadsheet_reader import read


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("A1*B1", Decimal("6")),
        ("SUM(A1:B1)", Decimal("5")),
        ("ROUND(1.235,2)", Decimal("1.24")),
        ("IF(A1<B1,10,20)", Decimal(10)),
        ("AVERAGE(A1:B1)", Decimal("2.5")),
        ("MAX(A1:B1)-MIN(A1:B1)", Decimal(1)),
        ("25%*4", Decimal(1)),
        ("ABS(-3)", Decimal(3)),
        ("COUNT(A1:B1)", Decimal(2)),
    ],
)
def test_safe_formula_subset(formula, expected):
    evaluator = FormulaEvaluator(
        {
            ("Sheet", "A1"): FormulaCell(Decimal(2)),
            ("Sheet", "B1"): FormulaCell(Decimal(3)),
            ("Sheet", "C1"): FormulaCell(formula=formula),
        }
    )
    result, provenance = evaluator.evaluate("Sheet", "C1")
    assert result == expected
    assert provenance["status"] == "calculated"


@pytest.mark.parametrize(
    "formula",
    [
        'WEBSERVICE("https://example.invalid")',
        "'[external.xlsx]Sheet'!A1",
        "CMD|'/C calc'!A1",
        "SUM(A1:A1048576)",
        "A1^1000000",
        "1/0",
        'INDIRECT("A1")',
        "C1+1",
        "SUM(A:A)",
        '__import__("os")',
        "SUM(A1 A2)",
    ],
)
def test_unsupported_external_circular_and_expensive_formulas_remain_explicit(formula):
    evaluator = FormulaEvaluator(
        {("Sheet", "A1"): FormulaCell(Decimal(2)), ("Sheet", "C1"): FormulaCell(formula=formula)}
    )
    with pytest.raises(UnsupportedFormula):
        evaluator.evaluate("Sheet", "C1")


def test_dependencies_cross_sheets_and_chains_preserve_inputs():
    evaluator = FormulaEvaluator(
        {
            ("Input Sheet", "A1"): FormulaCell(Decimal(4)),
            ("Result", "A1"): FormulaCell(formula="'Input Sheet'!A1*2"),
            ("Result", "B1"): FormulaCell(formula="A1+1"),
        }
    )
    value, provenance = evaluator.evaluate("Result", "B1")
    assert value == 9
    assert {d["sheet"] for d in provenance["inputs"]} == {"Input Sheet", "Result"}


def test_excel_errors_and_unsupported_conversions_are_not_silently_ignored():
    evaluator = FormulaEvaluator(
        {
            ("Sheet", "A1"): FormulaCell(error="Excel error"),
            ("Sheet", "C1"): FormulaCell(formula="SUM(A1:A2)"),
        }
    )
    with pytest.raises(UnsupportedFormula, match="Excel error"):
        evaluator.evaluate("Sheet", "C1")
    evaluator = FormulaEvaluator({("Sheet", "C1"): FormulaCell(formula='SUM("3",TRUE)')})
    with pytest.raises(UnsupportedFormula):
        evaluator.evaluate("Sheet", "C1")


def test_work_limit_is_shared_across_cells():
    evaluator = FormulaEvaluator(
        {("Sheet", "A1"): FormulaCell(formula="1+2"), ("Sheet", "A2"): FormulaCell(formula="3+4")},
        max_steps=3,
    )
    assert evaluator.evaluate("Sheet", "A1")[0] == 3
    with pytest.raises(UnsupportedFormula, match="work limit"):
        evaluator.evaluate("Sheet", "A2")


def test_shared_formulas_recalculate_stale_caches_and_preserve_provenance(tmp_path):
    book = Workbook()
    book.active.append([2, 3, "=A1*B1"])
    book.active.append([4, 5, "=A2*B2"])
    buffer = io.BytesIO()
    book.save(buffer)
    patched = io.BytesIO()
    with ZipFile(buffer) as original, ZipFile(patched, "w") as output:
        for name in original.namelist():
            data = original.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(
                    b"<f>A1*B1</f><v></v>", b'<f t="shared" si="0" ref="C1:C2">A1*B1</f><v>999</v>'
                )
                data = data.replace(b"<f>A2*B2</f><v></v>", b'<f t="shared" si="0"/><v>888</v>')
            output.writestr(name, data)
    units, store = read(tmp_path, patched.getvalue())
    cells = {c["cell"]: c for c in json.loads(store.get_text(units[0].metadata["cells_ref"]))}
    assert cells["C1"]["value"] == "6" and cells["C2"]["value"] == "20"
    assert cells["C2"]["formula"] == "A2*B2"
    assert cells["C1"]["calculation"]["cached_value"] == "999"
    assert cells["C2"]["calculation"]["inputs"][0]["cell"] == "A2"


def test_missing_caches_and_calculation_limit_have_explicit_statuses(tmp_path):
    book = Workbook()
    book.active.append([2, 3, "=A1*B1", '=WEBSERVICE("https://example.invalid")'])
    stream = io.BytesIO()
    book.save(stream)
    units, store = read(tmp_path / "normal", stream.getvalue())
    cells = json.loads(store.get_text(units[0].metadata["cells_ref"]))
    assert cells[2]["value"] == "6" and cells[2]["calculation"]["cached_value"] is None
    assert cells[3]["value"] is None and cells[3]["calculation"]["status"] == "unsupported"
    units, store = read(tmp_path / "limited", stream.getvalue(), max_formula_cells=2)
    assert "index limit" in units[0].metadata["conversion_warnings"][0]
