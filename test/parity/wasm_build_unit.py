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
    main,
    parse_exports,
    runtime_cache_path,
    type_declaration,
)
from scripts.wasm_export_scan_client import (
    MAX_PROCESS_SNAPSHOT_ROWS,
    PROCESS_RSS_LIMIT_BYTES,
    WasmExportScanClientError,
    _decode_build_payload,
    _decode_flatten_payload,
    _process_tree_rss_bytes,
    _validate_exports,
    run_export_scan,
    run_flatten_source,
)
from scripts.wasm_facade import js_input, js_output, ts_type


class WasmBindingsTests(unittest.TestCase):
    def test_int_is_a_wasm32_number_while_i64_stays_bigint(self) -> None:
        exports = parse_exports("export fn word(value: int) -> int = word_impl\nexport fn wide(value: i64) -> i64 = wide_impl")
        self.assertEqual(exports[0]["wasm_type"], "i32")
        self.assertEqual(exports[0]["parameters"][0]["wasm_type"], "i32")
        manifest = {"exports": exports, "target": "wasm32-unknown-unknown", "files": {"wasm": "demo.wasm"}}
        declarations = type_declaration(manifest, "demo")
        self.assertIn("word(value: number): number", declarations)
        self.assertIn("wide(value: bigint): bigint", declarations)

    def test_facade_preserves_narrow_integer_signedness(self) -> None:
        cases = (
            ("i8", "number", "((value << 24) >> 24)"),
            ("u8", "number", "((value) & 0xff)"),
            ("i16", "number", "((value << 16) >> 16)"),
            ("u16", "number", "((value) & 0xffff)"),
            ("i32", "number", "value"),
            ("u32", "number", "((value) >>> 0)"),
            ("i64", "bigint", "value"),
            ("u64", "bigint", "value"),
        )
        for abi_type, declaration_type, output_expression in cases:
            with self.subTest(abi_type=abi_type):
                self.assertEqual(ts_type(abi_type, "wasm32"), declaration_type)
                self.assertEqual(js_output(abi_type, "value"), output_expression)

        self.assertEqual(js_input("i64", "value"), "BigInt(value)")
        self.assertEqual(js_input("u64", "value"), "BigInt(value)")

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

    def test_facade_type_normalization_does_not_import_the_scanner(self) -> None:
        self.assertEqual(ts_type("mutable i64", "wasm32", parameter=True), "bigint")
        self.assertEqual(js_input("lmut i64", "value"), "BigInt(value)")
        self.assertEqual(js_output("heap u8", "value"), "((value) & 0xff)")

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

    def test_decodes_versioned_flatten_payload_without_exports(self) -> None:
        payload = {"version": 1, "flattened_source": 'include "part.elisa"\nexport fn answer()\n'}
        encoded = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        self.assertEqual(
            _decode_flatten_payload(encoded),
            'include "part.elisa"\nexport fn answer()\n',
        )

    def test_rejects_flatten_payload_with_extra_or_reordered_fields(self) -> None:
        for payload in (
            {"flattened_source": "source", "version": 1},
            {"version": 1, "flattened_source": "source", "exports": []},
        ):
            encoded = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
            with self.assertRaisesRegex(WasmExportScanClientError, "flatten payload shape"):
                _decode_flatten_payload(encoded)

    def test_flatten_client_selects_flatten_only_mode(self) -> None:
        payload = json.dumps(
            {"version": 1, "flattened_source": "no exports required\n"},
            separators=(",", ":"),
        ).encode() + b"\n"
        with (
            patch(
                "scripts.wasm_export_scan_client._scanner_command",
                return_value=["launcher", "scanner", "--flatten-payload", "source"],
            ) as command_builder,
            patch(
                "scripts.wasm_export_scan_client._capture_process_output",
                return_value=(0, payload, b""),
            ) as capture,
        ):
            self.assertEqual(
                run_flatten_source("launcher", "scanner", Path("/tmp/runtime.elisa")),
                "no exports required\n",
            )
        command_builder.assert_called_once_with(
            "launcher", "scanner", Path("/tmp/runtime.elisa"), "--flatten-payload"
        )
        capture.assert_called_once_with(
            ["launcher", "scanner", "--flatten-payload", "source"]
        )

    def test_export_client_selects_component_payload_when_requested(self) -> None:
        self.row["return"] = "WindowState"
        self.row["parameters"] = [
            {
                "name": "state",
                "type": "WindowState",
                "default": None,
                "binding": "scalar",
                "wasm_type": "i32",
            }
        ]
        payload = self.encode()
        with (
            patch(
                "scripts.wasm_export_scan_client._scanner_command",
                return_value=["launcher", "scanner", "--build-component-payload", "source"],
            ) as command_builder,
            patch(
                "scripts.wasm_export_scan_client._capture_process_output",
                return_value=(0, payload, b""),
            ) as capture,
        ):
            self.assertEqual(
                run_export_scan("launcher", "scanner", Path("/tmp/module.elisa"), component=True),
                ("export fn answer() -> i32 = answer_impl\n", [self.row]),
            )
        command_builder.assert_called_once_with(
            "launcher", "scanner", Path("/tmp/module.elisa"), "--build-component-payload"
        )
        capture.assert_called_once_with(
            ["launcher", "scanner", "--build-component-payload", "source"]
        )
        with self.assertRaisesRegex(WasmExportScanClientError, "inconsistent scanner payload ABI"):
            _decode_build_payload(payload)

    def test_export_client_keeps_ordinary_build_payload_by_default(self) -> None:
        payload = self.encode()
        with (
            patch(
                "scripts.wasm_export_scan_client._scanner_command",
                return_value=["launcher", "scanner", "--build-payload", "source"],
            ) as command_builder,
            patch(
                "scripts.wasm_export_scan_client._capture_process_output",
                return_value=(0, payload, b""),
            ) as capture,
        ):
            self.assertEqual(
                run_export_scan("launcher", "scanner", Path("/tmp/module.elisa")),
                ("export fn answer() -> i32 = answer_impl\n", [self.row]),
            )
        command_builder.assert_called_once_with(
            "launcher", "scanner", Path("/tmp/module.elisa"), "--build-payload"
        )
        capture.assert_called_once_with(
            ["launcher", "scanner", "--build-payload", "source"]
        )

    def test_rss_sampler_sums_process_group_and_descendant_tree(self) -> None:
        process = SimpleNamespace(pid=100)
        snapshot = "100 1 100 10\n101 100 100 20\n102 101 102 30\n200 1 200 99\n"
        completed = SimpleNamespace(returncode=0, stdout=snapshot)
        with patch("scripts.wasm_export_scan_client.subprocess.run", return_value=completed):
            self.assertEqual(_process_tree_rss_bytes(process), (10 + 20 + 30) * 1024)

    def test_rss_sampler_fails_closed_on_malformed_snapshot(self) -> None:
        process = SimpleNamespace(pid=100)
        completed = SimpleNamespace(returncode=0, stdout="100 1 100 not-a-number\n")
        with patch("scripts.wasm_export_scan_client.subprocess.run", return_value=completed):
            self.assertIsNone(_process_tree_rss_bytes(process))

    def test_rss_guard_constants_are_bounded(self) -> None:
        self.assertEqual(PROCESS_RSS_LIMIT_BYTES, 512 * 1024 * 1024)
        self.assertEqual(MAX_PROCESS_SNAPSHOT_ROWS, 65536)

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

    def test_rejects_aggregate_parameter_count_over_limit(self) -> None:
        def make_export(index: int, parameter_count: int) -> dict[str, object]:
            parameters = [
                {
                    "name": f"p{parameter_index}",
                    "type": "u8",
                    "default": None,
                    "binding": "scalar",
                    "wasm_type": "i32",
                }
                for parameter_index in range(parameter_count)
            ]
            return {
                "name": f"export_{index}",
                "target": f"target_{index}",
                "parameters": parameters,
                "return": "void",
                "binding": "scalar",
                "wasm_type": "void",
                "line": index + 1,
            }

        exports = [make_export(index, 4096) for index in range(4)]
        exports.append(make_export(4, 1))
        with self.assertRaisesRegex(WasmExportScanClientError, "total parameters"):
            _validate_exports(exports)

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
    def test_cli_uses_elisascript_scanner_environment_defaults(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "ELISASCRIPT_PUBLIC_LAUNCHER": "/opt/elisa/bin/elisascript",
                    "ELISASCRIPT_EXPORT_SCAN_SCRIPT": "/opt/elisa/scripts/wasm_export_scan.elisascript",
                },
                clear=True,
            ),
            patch(
                "sys.argv",
                [
                    "wasm_build.py",
                    "--root",
                    "/tmp/root",
                    "--compiler",
                    "/tmp/compiler",
                    "--source",
                    "/tmp/input.elisa",
                    "--output",
                    "/tmp/output.wasm",
                ],
            ),
            patch("scripts.wasm_build.build") as build,
        ):
            self.assertEqual(main(), 0)
        args = build.call_args.args[0]
        self.assertEqual(args.export_scan_launcher, "/opt/elisa/bin/elisascript")
        self.assertEqual(
            args.export_scan_script,
            "/opt/elisa/scripts/wasm_export_scan.elisascript",
        )

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
        # `component=` arrived with enum exports in component mode (ee50240f); the default
        # path passes it explicitly, so the bare-argument expectation no longer matches.
        parse_source.assert_called_once_with(flattened, component=False)

    def test_opt_in_uses_elisascript_without_loading_python_scanner(self) -> None:
        source_path = Path("/tmp/input.elisa")
        flattened = "export fn answer() -> i32 = answer_impl\n"
        exports = [{"name": "answer"}]
        args = SimpleNamespace(
            export_scan_launcher="/usr/bin/elisac",
            export_scan_script="/tmp/wasm_export_scan.elisascript",
        )
        with (
            patch(
                "scripts.wasm_build._python_export_scanner",
                side_effect=AssertionError("opt-in path loaded the Python scanner"),
            ),
            patch("scripts.wasm_build.run_export_scan", return_value=(flattened, exports)) as scan,
        ):
            self.assertEqual(load_export_scan(source_path, args), (flattened, exports))
        scan.assert_called_once_with(
            "/usr/bin/elisac",
            "/tmp/wasm_export_scan.elisascript",
            source_path,
            component=False,
        )

    def test_opt_in_passes_component_mode_to_elisascript_scanner(self) -> None:
        source_path = Path("/tmp/input.elisa")
        flattened = "export fn open() -> u32 = open_impl\n"
        exports = [{"name": "open"}]
        args = SimpleNamespace(
            export_scan_launcher="/usr/bin/elisac",
            export_scan_script="/tmp/wasm_export_scan.elisascript",
            component_types=["Widget"],
        )
        with patch(
            "scripts.wasm_build.run_export_scan", return_value=(flattened, exports)
        ) as scan:
            self.assertEqual(load_export_scan(source_path, args), (flattened, exports))
        scan.assert_called_once_with(
            "/usr/bin/elisac",
            "/tmp/wasm_export_scan.elisascript",
            source_path,
            component=True,
        )

    def test_runtime_cache_uses_elisascript_flatten_payload_when_configured(self) -> None:
        root = Path("/tmp/elisa-wasm-runtime-cache-test")
        runtime_source = root / "runtime.elisa"
        with (
            patch("scripts.wasm_build.run_flatten_source", return_value="flattened") as flatten,
            patch("scripts.wasm_build.read_flat_source") as python_flatten,
        ):
            runtime_cache_path(
                root,
                root / "compiler",
                "wasm32-test",
                runtime_source,
                export_scan_launcher="/usr/bin/elisac",
                export_scan_script="/tmp/wasm_export_scan.elisascript",
            )
        flatten.assert_called_once_with(
            "/usr/bin/elisac",
            "/tmp/wasm_export_scan.elisascript",
            runtime_source,
        )
        python_flatten.assert_not_called()

    def test_opt_in_launcher_and_script_must_be_paired(self) -> None:
        args = SimpleNamespace(export_scan_launcher="/bin/elisac")
        with self.assertRaisesRegex(WasmBuildError, "must be supplied together"):
            load_export_scan(Path("/tmp/input.elisa"), args)


if __name__ == "__main__":
    unittest.main()
