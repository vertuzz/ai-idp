"""Inert, bounded spreadsheet arithmetic. No Python evaluation or external access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext
from typing import Any

from openpyxl.formula import Tokenizer
from openpyxl.formula.tokenizer import TokenizerError
from openpyxl.utils.cell import get_column_letter, range_boundaries


class UnsupportedFormula(ValueError):
    pass


@dataclass
class FormulaCell:
    value: Any = None
    formula: str | None = None
    error: str | None = None


class FormulaEvaluator:
    """A deliberately small Excel subset with workbook-wide work and dependency caps."""

    def __init__(self, cells: dict[tuple[str, str], FormulaCell], *, max_steps: int = 100_000):
        self.cells = cells
        self.sheets = {sheet for sheet, _ in cells}
        self.steps = max_steps
        self.results: dict[tuple[str, str], tuple[Any, dict[str, Any]]] = {}
        self.active: set[tuple[str, str]] = set()

    def evaluate(self, sheet: str, cell: str) -> tuple[Any, dict[str, Any]]:
        key = (sheet, cell)
        if key in self.results:
            return self.results[key]
        original = self.cells.get(key, FormulaCell())
        if original.error:
            raise UnsupportedFormula(original.error)
        if original.formula is None:
            return original.value, {}
        if key in self.active or len(self.active) >= 32:
            raise UnsupportedFormula("Circular or excessively deep formula dependencies.")
        if len(original.formula) > 4096:
            raise UnsupportedFormula("Formula text exceeds the calculation limit.")
        self.active.add(key)
        dependencies: dict[tuple[str, str], Any] = {}
        try:
            tokens = [t for t in Tokenizer("=" + original.formula).items if t.type != "WHITE-SPACE"]
            if len(tokens) > 512:
                raise UnsupportedFormula("Formula token limit exceeded.")
            position = 0

            def take() -> Any:
                nonlocal position
                self.steps -= 1
                if self.steps < 0 or position >= len(tokens):
                    raise UnsupportedFormula("Formula work limit or incomplete expression.")
                token = tokens[position]
                position += 1
                return token

            def reference(text: str) -> Any:
                target_sheet = sheet
                if "!" in text:
                    target_sheet, text = text.rsplit("!", 1)
                    target_sheet = target_sheet.strip("'").replace("''", "'")
                if target_sheet not in self.sheets:
                    raise UnsupportedFormula("Unknown worksheet reference.")
                if not re.fullmatch(
                    r"\$?[A-Za-z]{1,3}\$?[1-9]\d*(?::\$?[A-Za-z]{1,3}\$?[1-9]\d*)?", text
                ):
                    raise UnsupportedFormula(
                        "Only local A1 references and bounded ranges are supported."
                    )
                left, top, right, bottom = range_boundaries(text.replace("$", "").upper())
                if not (1 <= left <= right <= 16384 and 1 <= top <= bottom <= 1048576):
                    raise UnsupportedFormula("Invalid worksheet coordinates.")
                if (right - left + 1) * (bottom - top + 1) > 128:
                    raise UnsupportedFormula("Formula range exceeds the dependency limit.")
                values = []
                for row in range(top, bottom + 1):
                    for column in range(left, right + 1):
                        self.steps -= 1
                        if self.steps < 0 or len(dependencies) >= 128:
                            raise UnsupportedFormula("Formula dependency/work limit exceeded.")
                        address = get_column_letter(column) + str(row)
                        dep_key = (target_sheet, address)
                        value, provenance = self.evaluate(*dep_key)
                        dependencies[dep_key] = value
                        for dependency in provenance.get("inputs", []):
                            dependencies[(dependency["sheet"], dependency["cell"])] = dependency[
                                "value"
                            ]
                        if len(dependencies) > 128:
                            raise UnsupportedFormula("Formula dependency limit exceeded.")
                        values.append(value)
                return values if ":" in text else values[0]

            def expression(minimum: int = 0, depth: int = 0) -> Any:
                if depth > 32:
                    raise UnsupportedFormula("Formula expression depth exceeded.")
                token = take()
                if token.type == "OPERATOR-PREFIX" and token.value in {"+", "-"}:
                    value = number(expression(6, depth + 1))
                    if token.value == "-":
                        value = -value
                elif token.type == "PAREN" and token.subtype == "OPEN":
                    value = expression(0, depth + 1)
                    close = take()
                    if close.type != "PAREN" or close.subtype != "CLOSE":
                        raise UnsupportedFormula("Unbalanced parentheses.")
                elif token.type == "FUNC" and token.subtype == "OPEN":
                    arguments = []
                    if position < len(tokens) and tokens[position].subtype != "CLOSE":
                        while True:
                            arguments.append(expression(0, depth + 1))
                            if position >= len(tokens) or tokens[position].type != "SEP":
                                break
                            if take().subtype != "ARG":
                                raise UnsupportedFormula("Unsupported formula separator.")
                    close = take()
                    if close.type != "FUNC" or close.subtype != "CLOSE":
                        raise UnsupportedFormula("Unbalanced function arguments.")
                    value = function(token.value[:-1].upper(), arguments)
                elif token.type == "OPERAND":
                    if token.subtype == "NUMBER":
                        value = checked(Decimal(token.value))
                    elif token.subtype == "LOGICAL":
                        value = token.value == "TRUE"
                    elif token.subtype == "TEXT":
                        value = token.value[1:-1].replace('""', '"')
                    elif token.subtype == "RANGE":
                        value = reference(token.value)
                    else:
                        raise UnsupportedFormula("Error/unsupported operand in formula.")
                else:
                    raise UnsupportedFormula("Unsupported formula syntax.")
                precedence = {
                    "=": 1,
                    "<>": 1,
                    "<": 1,
                    ">": 1,
                    "<=": 1,
                    ">=": 1,
                    "+": 3,
                    "-": 3,
                    "*": 4,
                    "/": 4,
                    "^": 5,
                }
                while position < len(tokens):
                    token = tokens[position]
                    if token.type == "OPERATOR-POSTFIX" and token.value == "%":
                        take()
                        value = number(value) / 100
                        continue
                    priority = (
                        precedence.get(token.value, -1) if token.type == "OPERATOR-INFIX" else -1
                    )
                    if priority < minimum:
                        break
                    operation = take().value
                    other = expression(priority + 1, depth + 1)
                    value = binary(operation, value, other)
                return value

            with localcontext() as context:
                context.prec = 28
                value = expression()
                if position != len(tokens) or isinstance(value, list):
                    raise UnsupportedFormula("Unsupported trailing expression or array result.")
                if isinstance(value, Decimal):
                    value = checked(value)
            result = (
                value,
                {
                    "status": "calculated",
                    "engine": "bounded-arithmetic-v1",
                    "inputs": [
                        {"sheet": s, "cell": c, "value": str(v) if isinstance(v, Decimal) else v}
                        for (s, c), v in dependencies.items()
                    ],
                },
            )
            self.results[key] = result
            return result
        except (
            TokenizerError,
            DecimalException,
            ArithmeticError,
            ValueError,
            IndexError,
            TypeError,
        ) as error:
            raise UnsupportedFormula(str(error) or "Formula calculation failed.") from error
        finally:
            self.active.remove(key)


def checked(value: Decimal) -> Decimal:
    if not value.is_finite() or abs(value) > Decimal("1e100"):
        raise UnsupportedFormula("Formula numeric magnitude limit exceeded.")
    return value


def number(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    if not isinstance(value, (Decimal, int, float)):
        raise UnsupportedFormula("Non-numeric operand; implicit text conversion is unsupported.")
    return checked(Decimal(str(value)))


def binary(operation: str, left: Any, right: Any) -> Any:
    if operation in {"=", "<>", "<", ">", "<=", ">="}:
        if isinstance(left, str) and isinstance(right, str):
            left, right = left.casefold(), right.casefold()
        elif isinstance(left, bool) and isinstance(right, bool):
            pass
        elif isinstance(left, (str, bool)) or isinstance(right, (str, bool)):
            raise UnsupportedFormula("Mixed-type comparisons are unsupported.")
        else:
            left, right = number(left), number(right)
        return {
            "=": left == right,
            "<>": left != right,
            "<": left < right,
            ">": left > right,
            "<=": left <= right,
            ">=": left >= right,
        }[operation]
    a, b = number(left), number(right)
    if operation == "+":
        return checked(a + b)
    if operation == "-":
        return checked(a - b)
    if operation == "*":
        return checked(a * b)
    if operation == "/":
        return checked(a / b)
    if operation == "^" and b == b.to_integral() and abs(b) <= 100:
        return checked(a ** int(b))
    raise UnsupportedFormula("Unsupported exponent or operator.")


def function(name: str, arguments: list[Any]) -> Any:
    if name in {"SUM", "AVERAGE", "MIN", "MAX", "COUNT"} and any(
        not isinstance(argument, (list, Decimal, int, float)) or isinstance(argument, bool)
        for argument in arguments
    ):
        raise UnsupportedFormula("Implicit scalar text/logical conversions are unsupported.")
    flattened = [
        v
        for argument in arguments
        for v in (argument if isinstance(argument, list) else [argument])
    ]
    numeric = [
        number(v)
        for v in flattened
        if isinstance(v, (Decimal, int, float)) and not isinstance(v, bool)
    ]
    if name in {"SUM", "AVERAGE", "MIN", "MAX", "COUNT"}:
        if name == "COUNT":
            return Decimal(len(numeric))
        if name == "SUM":
            return checked(sum(numeric, Decimal(0)))
        if not numeric:
            if name in {"MIN", "MAX"}:
                return Decimal(0)
            raise UnsupportedFormula("AVERAGE has no numeric inputs.")
        return checked(
            {
                "AVERAGE": lambda: sum(numeric) / len(numeric),
                "MIN": lambda: min(numeric),
                "MAX": lambda: max(numeric),
            }[name]()
        )
    if name == "ABS" and len(arguments) == 1:
        return abs(number(arguments[0]))
    if name == "ROUND" and len(arguments) == 2:
        precision = number(arguments[1])
        if precision != precision.to_integral() or abs(precision) > 20:
            raise UnsupportedFormula("ROUND precision exceeds its limit.")
        return number(arguments[0]).quantize(
            Decimal(1).scaleb(-int(precision)), rounding=ROUND_HALF_UP
        )
    # IF is deliberately eager: unsupported/error expressions in either branch
    # remain unsupported instead of silently claiming complete Excel semantics.
    if name == "IF" and len(arguments) == 3 and isinstance(arguments[0], bool):
        return arguments[1] if arguments[0] else arguments[2]
    raise UnsupportedFormula("Unsupported function or argument signature: " + name)
