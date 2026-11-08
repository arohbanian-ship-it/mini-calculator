"""Headless regression checks for the calculator's display transformations."""
import ast
from pathlib import Path
import re
import unittest


class FormattingTests(unittest.TestCase):
    def setUp(self):
        source_file = Path(__file__).resolve().parents[1] / "mini_calculator.pyw"
        module = ast.parse(source_file.read_text(encoding="utf-8"))
        wanted = {
            "canonicalize_operator_symbols",
            "format_operator_symbols",
            "format_operator_spacing_token",
            "format_operator_spacing_text",
            "map_offset_after_operator_spacing",
        }
        definitions = [
            item for item in module.body
            if isinstance(item, ast.FunctionDef) and item.name in wanted
        ]
        self.assertEqual(len(wanted), len(definitions))
        self.env = {
            "re": re,
            "THIN_SPACE": "\u2009",
            "SPACED_OPERATOR_CHARS": "+-*/×÷=",
            "use_multiplication_symbol": False,
            "use_division_symbol": False,
            "space_around_operators": True,
            "is_displayed_calculation_part": lambda text: True,
        }
        exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source_file), "exec"), self.env)

    def test_independent_symbol_options(self):
        display = self.env["format_operator_symbols"]
        self.assertEqual(display("3*4/2"), "3*4/2")
        self.env["use_multiplication_symbol"] = True
        self.assertEqual(display("3*4/2"), "3×4/2")
        self.env["use_division_symbol"] = True
        self.assertEqual(display("3*4/2"), "3×4÷2")
        self.env["use_multiplication_symbol"] = False
        self.assertEqual(display("3*4/2"), "3*4÷2")
        self.assertEqual(self.env["canonicalize_operator_symbols"]("3×4÷2"), "3*4/2")

    def test_spacing_switch(self):
        space = "\u2009"
        display = self.env["format_operator_spacing_text"]
        self.assertEqual(display("12+34"), "12" + space + "+" + space + "34")
        self.env["space_around_operators"] = False
        self.assertEqual(display("12" + space + "+" + space + "34"), "12+34")

    def test_unary_and_exponent(self):
        display = self.env["format_operator_spacing_token"]
        space = "\u2009"
        self.assertEqual(display("-3+4"), "-3" + space + "+" + space + "4")
        self.assertEqual(display("2**3+1"), "2**3" + space + "+" + space + "1")

    def test_cursor_offset_after_spacing(self):
        original = "12+34"
        formatted = self.env["format_operator_spacing_text"](original)
        mapped = self.env["map_offset_after_operator_spacing"](original, formatted, 3)
        self.assertEqual(formatted[:mapped].replace("\u2009", ""), "12+")


if __name__ == "__main__":
    unittest.main()
