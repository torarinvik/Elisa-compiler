#!/usr/bin/env python3
"""Focused tests for the host-side WASM ABI and binding generator."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.wasm_build import (
    WasmBuildError,
    js_bindings,
    load_export_scan,
    parse_exports,
    type_declaration,
)
from scripts.wasm_export_scan_client import WasmExportScanClientError, _decode_build_payload


class WasmBindingsTests(unittest.TestCase):
    def test_int_is_a_wasm32_number_while_i64_stays_bigint(self) -> None:
        exports = parse_exports("export fn word(value: int) -> int = word_impl\nexport fn wide(value: i64) -> i64 = wide_impl")
        self.assertEqual(exports[0]["wasm_type"], "i32")
        self.assertEqual(exports[0]["parameters"][0]["wasm_type"], "i32")
        manifest = {"exports": exports, "target": "wasm32-unknown-unknown", "files": {"wasm": "demo.wasm"}}
        declarations = type_declaration(manifest, "demo")
        self.assertIn("word(value: number): number", declarations)
        self.assertIn("wide(value: bigint): bigint", declarations)

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

    def test_link_name_is_preserved_for_wit_component_exports(self) -> None:
        exports = parse_exports(
            '@link_name("example:window/guest@0.1.0#start")\n'
            "export fn start(width: u32, height: u32) -> void = start_impl\n"
        )
        self.assertEqual(exports[0]["name"], "start")
        self.assertEqual(exports[0]["link_name"], "example:window/guest@0.1.0#start")


class WasmExportScanClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {
            "name": "answer",
            "target": "answer_impl",
            "parameters": [],
            "return": "i32",
            "binding": "scalar",
            "wasm_type": "i32",
            "line": 1,
        }

    def encode(self, *, version: object = 1) -> bytes:
        payload = {
            "version": version,
            "flattened_source": "export fn answer() -> i32 = answer_impl\n",
            "exports": [self.row],
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"

    def test_decodes_ordered_versioned_build_payload(self) -> None:
        source, exports = _decode_build_payload(self.encode())
        self.assertEqual(source, "export fn answer() -> i32 = answer_impl\n")
        self.assertEqual(exports, [self.row])

    def test_rejects_boolean_payload_version(self) -> None:
        with self.assertRaisesRegex(WasmExportScanClientError, "unsupported payload version"):
            _decode_build_payload(self.encode(version=True))

    def test_rejects_duplicate_json_keys(self) -> None:
        payload = (
            b'{"version":1,"version":1,"flattened_source":"x",'
            b'"exports":[{"name":"answer","target":"answer_impl",'
            b'"parameters":[],"return":"i32","binding":"scalar",'
            b'"wasm_type":"i32","line":1}]}\n'
        )
        with self.assertRaisesRegex(WasmExportScanClientError, "invalid JSON"):
            _decode_build_payload(payload)

    def test_rejects_reordered_export_fields(self) -> None:
        row = dict(reversed(list(self.row.items())))
        payload = {
            "version": 1,
            "flattened_source": "export fn answer() -> i32 = answer_impl\n",
            "exports": [row],
        }
        with self.assertRaisesRegex(WasmExportScanClientError, "field order"):
            _decode_build_payload(json.dumps(payload, separators=(",", ":")).encode() + b"\n")

    def test_rejects_export_names_that_are_not_identifiers(self) -> None:
        self.row["name"] = "answer);globalThis.pwned=("
        with self.assertRaisesRegex(WasmExportScanClientError, r"exports\[0\].name"):
            _decode_build_payload(self.encode())

    def test_rejects_targets_that_are_not_scanner_identifiers(self) -> None:
        self.row["target"] = "answer.impl"
        with self.assertRaisesRegex(WasmExportScanClientError, r"exports\[0\].target"):
            _decode_build_payload(self.encode())

    def test_rejects_return_abi_inconsistent_with_return_type(self) -> None:
        self.row["binding"] = "pointer"
        with self.assertRaisesRegex(WasmExportScanClientError, "inconsistent scanner payload ABI"):
            _decode_build_payload(self.encode())

    def test_rejects_invalid_or_duplicate_parameter_names(self) -> None:
        self.row["parameters"] = [
            {
                "name": "x,evil",
                "type": "i32",
                "default": None,
                "binding": "scalar",
                "wasm_type": "i32",
            }
        ]
        with self.assertRaisesRegex(WasmExportScanClientError, r"parameters\[0\].name"):
            _decode_build_payload(self.encode())

        self.row["parameters"] = [
            {
                "name": "x",
                "type": "i32",
                "default": None,
                "binding": "scalar",
                "wasm_type": "i32",
            },
            {
                "name": "x",
                "type": "i32",
                "default": None,
                "binding": "scalar",
                "wasm_type": "i32",
            },
        ]
        with self.assertRaisesRegex(WasmExportScanClientError, "duplicate parameter name"):
            _decode_build_payload(self.encode())

    def test_rejects_parameter_abi_inconsistent_with_type(self) -> None:
        self.row["parameters"] = [
            {
                "name": "value",
                "type": "cstr",
                "default": None,
                "binding": "scalar",
                "wasm_type": "i32",
            }
        ]
        with self.assertRaisesRegex(WasmExportScanClientError, "inconsistent scanner payload ABI"):
            _decode_build_payload(self.encode())

    def test_rejects_non_utf8_parameter_defaults(self) -> None:
        self.row["parameters"] = [
            {
                "name": "value",
                "type": "i32",
                "default": "\ud800",
                "binding": "scalar",
                "wasm_type": "i32",
            }
        ]
        with self.assertRaisesRegex(WasmExportScanClientError, "invalid UTF-8 scanner payload field"):
            _decode_build_payload(self.encode())

    def test_empty_link_name_matches_scanner_schema(self) -> None:
        self.row["link_name"] = ""
        _source, exports = _decode_build_payload(self.encode())
        self.assertEqual(exports[0]["link_name"], "")


class ExportScannerSelectionTests(unittest.TestCase):
    def test_default_keeps_the_python_scanner_path(self) -> None:
        source_path = Path("/tmp/input.elisa")
        flattened = "export fn answer() -> i32 = answer_impl\n"
        exports = [{"name": "answer"}]
        with (
            patch("scripts.wasm_build.read_flat_source", return_value=flattened) as read_source,
            patch("scripts.wasm_build.parse_exports", return_value=exports) as parse_source,
        ):
            self.assertEqual(load_export_scan(source_path, SimpleNamespace()), (flattened, exports))
        read_source.assert_called_once_with(source_path)
        parse_source.assert_called_once_with(flattened)

    def test_opt_in_launcher_and_script_must_be_paired(self) -> None:
        args = SimpleNamespace(export_scan_launcher="/bin/elisac")
        with self.assertRaisesRegex(WasmBuildError, "must be supplied together"):
            load_export_scan(Path("/tmp/input.elisa"), args)


if __name__ == "__main__":
    unittest.main()
