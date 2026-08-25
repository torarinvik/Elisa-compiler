#!/usr/bin/env python3
"""Focused tests for the host-side WASM ABI and binding generator."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.wasm_build import WasmBuildError, js_bindings, parse_exports, type_declaration


class WasmBindingsTests(unittest.TestCase):
    def test_cstr_is_a_high_level_string_binding(self) -> None:
        exports = parse_exports("export fn echo(value: cstr) -> cstr = echo_impl")
        self.assertEqual(exports[0]["parameters"][0]["binding"], "string")
        manifest = {"exports": exports, "target": "wasm32-unknown-unknown", "memory_initial_pages": 16, "memory_max_pages": 32, "files": {"wasm": "demo.wasm"}}
        generated = js_bindings(manifest, "demo")
        self.assertIn('typeof value === "string"', generated)
        self.assertIn("memoryTools.free(__elisa_value)", generated)
        self.assertIn("Missing Elisa WASM imports", generated)
        declarations = type_declaration(manifest, "demo")
        self.assertIn("echo(value: string | number): string", declarations)

    def test_hyphenated_output_gets_a_valid_typescript_interface(self) -> None:
        manifest = {"exports": parse_exports("export fn answer() -> i32 = answer_impl"), "target": "wasm32-unknown-unknown"}
        declarations = type_declaration(manifest, "physics-engine")
        self.assertIn("interface physics_engineExports", declarations)

    def test_aggregate_export_has_an_actionable_error(self) -> None:
        with self.assertRaisesRegex(WasmBuildError, "export a scalar or pointer adapter"):
            parse_exports("export fn bad(values: darray[i32]) -> i32 = bad_impl")

    def test_duplicate_exports_are_rejected(self) -> None:
        source = "export fn same() -> i32 = first\nexport fn same() -> i32 = second\n"
        with self.assertRaisesRegex(WasmBuildError, "duplicate WASM export"):
            parse_exports(source)


if __name__ == "__main__":
    unittest.main()
