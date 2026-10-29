#!/usr/bin/env python3
"""Focused tests for the host-side WASM ABI and binding generator."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.wasm_build import (
    WasmBuildError,
    build,
    js_bindings,
    load_export_scan,
    main,
    parse_exports,
    read_flat_source,
    runtime_cache_path,
    type_declaration,
    write_text_if_changed,
    _resolve_llc_executable,
    _resolve_native_object_merger,
    _runtime_cache_entry_valid,
    _runtime_cache_observer_requested,
    _runtime_cache_directory_ready,
    _runtime_object_from_cache,
    _publish_runtime_cache,
)
from scripts.wasm_export_scan_client import (
    MAX_PROCESS_SNAPSHOT_BYTES,
    MAX_PROCESS_SNAPSHOT_ROWS,
    PROCESS_RSS_LIMIT_BYTES,
    WasmExportScanClientError,
    _decode_build_payload,
    _decode_flatten_payload,
    _process_tree_rss_bytes,
    _read_process_snapshot,
    _validate_exports,
    run_export_scan,
    run_flatten_source,
)
from scripts.wasm_export_scan import MAX_FLATTENED_SOURCE_BYTES, MAX_SOURCE_LINES
from scripts.wasm_facade import js_input, js_output, ts_type


_BOUNDED_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "wasm_bounded_stage1_command",
    ROOT / "test/parity/run_bounded_stage1_command.py",
)
assert _BOUNDED_RUNNER_SPEC is not None
assert _BOUNDED_RUNNER_SPEC.loader is not None
bounded_runner = importlib.util.module_from_spec(_BOUNDED_RUNNER_SPEC)
sys.modules[_BOUNDED_RUNNER_SPEC.name] = bounded_runner
_BOUNDED_RUNNER_SPEC.loader.exec_module(bounded_runner)


class WasmBindingsTests(unittest.TestCase):
    def test_generated_text_write_preserves_unchanged_output_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.mjs"
            self.assertTrue(write_text_if_changed(path, "export {};\n"))
            expected_mtime = 1_600_000_000_123_456_789
            os.utime(path, ns=(expected_mtime, expected_mtime))
            original_mtime = path.stat().st_mtime_ns

            self.assertFalse(write_text_if_changed(path, "export {};\n"))
            self.assertEqual(path.stat().st_mtime_ns, original_mtime)
            self.assertTrue(write_text_if_changed(path, "export const changed = true;\n"))
            self.assertEqual(path.read_bytes(), b"export const changed = true;\n")

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
        echo_binding = generated[generated.index("    echo(value) {"):]
        self.assertLess(
            echo_binding.index("return memoryTools.readString("),
            echo_binding.index("memoryTools.free(__elisa_value)"),
        )
        self.assertIn("Missing Elisa WASM imports", generated)
        self.assertIn('if (end >= data.length) throw new RangeError("Elisa WASM C string pointer is outside linear memory")', generated)
        self.assertIn('if (end === data.length) throw new RangeError("Elisa WASM C string is not NUL terminated")', generated)
        declarations = type_declaration(manifest, "demo")
        self.assertIn("echo(value: string | number): string", declarations)

        pair_exports = parse_exports("export fn pair(left: cstr, right: cstr) -> cstr = pair_impl")
        pair_manifest = {
            "exports": pair_exports,
            "target": "wasm32-unknown-unknown",
            "memory_initial_pages": 16,
            "memory_max_pages": 32,
            "files": {"wasm": "demo.wasm"},
        }
        pair_generated = js_bindings(pair_manifest, "demo")
        pair_binding = pair_generated[pair_generated.index("    pair(left, right) {"):]
        self.assertLess(pair_binding.index("try {"), pair_binding.index("__elisa_left = typeof left"))
        self.assertLess(pair_binding.index("try {"), pair_binding.index("__elisa_right = typeof right"))
        self.assertIn('typeof left === "string" && __elisa_left !== undefined', pair_binding)
        self.assertIn('typeof right === "string" && __elisa_right !== undefined', pair_binding)

    def test_facade_type_normalization_does_not_import_the_scanner(self) -> None:
        self.assertEqual(ts_type("mutable i64", "wasm32", parameter=True), "bigint")
        self.assertEqual(js_input("lmut i64", "value"), "BigInt(value)")
        self.assertEqual(js_output("heap u8", "value"), "((value) & 0xff)")

    def test_hyphenated_output_gets_a_valid_typescript_interface(self) -> None:
        manifest = {"exports": parse_exports("export fn answer() -> i32 = answer_impl"), "target": "wasm32-unknown-unknown"}
        declarations = type_declaration(manifest, "physics-engine")
        self.assertIn("interface physics_engineExports", declarations)

    def test_non_ascii_output_name_normalizes_by_unicode_codepoint(self) -> None:
        manifest = {"exports": [], "target": "wasm32-unknown-unknown"}
        declarations = type_declaration(manifest, "é🌲")
        self.assertIn("interface __Exports", declarations)
        self.assertNotIn("interface ______Exports", declarations)

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


class WasmReferenceSourceBoundsTests(unittest.TestCase):
    def test_reference_scanner_flattens_nested_includes_in_order_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-reference-nested-") as temporary:
            root = Path(temporary)
            source = root / "root.elisa"
            middle = root / "middle.elisa"
            leaf = root / "leaf.elisa"
            source.write_text('root-before\ninclude "middle.elisa"\nroot-after\ninclude "leaf.elisa"\n')
            middle.write_text('middle-before\ninclude "leaf.elisa"\nmiddle-after\n')
            leaf.write_text("leaf\n")

            self.assertEqual(
                read_flat_source(source),
                "root-before\nmiddle-before\nleaf\nmiddle-after\nroot-after\n",
            )

    def test_reference_scanner_preserves_symlink_includes_and_newline_normalization(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-reference-source-") as temporary:
            root = Path(temporary)
            target = root / "target.elisa"
            link = root / "link.elisa"
            source = root / "root.elisa"
            target.write_bytes(b"export fn answer() -> i32 = answer_impl\r\n")
            link.symlink_to(target)
            source.write_bytes(b'include "link.elisa"\r\n')

            self.assertEqual(
                read_flat_source(source),
                "export fn answer() -> i32 = answer_impl\n",
            )

    def test_reference_scanner_rejects_oversized_source_before_reading_it_all(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-reference-source-limit-") as temporary:
            source = Path(temporary) / "large.elisa"
            source.write_bytes(b"x" * (MAX_FLATTENED_SOURCE_BYTES + 1))

            with self.assertRaisesRegex(WasmBuildError, "flattened source exceeds"):
                read_flat_source(source)

    def test_reference_scanner_preserves_order_through_nested_includes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-reference-nested-") as temporary:
            root = Path(temporary)
            depth = 128
            leaf_text = "leaf-" + ("x" * (1 << 20)) + "\n"
            (root / f"level-{depth}.elisa").write_text(leaf_text, encoding="utf-8")
            for index in reversed(range(depth)):
                (root / f"level-{index}.elisa").write_text(
                    f"head-{index}\ninclude \"level-{index + 1}.elisa\"\ntail-{index}\n",
                    encoding="utf-8",
                )

            expected = (
                "".join(f"head-{index}\n" for index in range(depth))
                + leaf_text
                + "".join(f"tail-{index}\n" for index in reversed(range(depth)))
            )
            self.assertEqual(read_flat_source(root / "level-0.elisa"), expected)

    def test_reference_scanner_caps_newline_heavy_object_count(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-reference-lines-") as temporary:
            source = Path(temporary) / "many-lines.elisa"
            source.write_bytes(b"\n" * (MAX_SOURCE_LINES + 1))

            with self.assertRaisesRegex(WasmBuildError, "closure exceeds .* lines"):
                read_flat_source(source)

    def test_reference_scanner_does_not_block_on_fifo(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable on this platform")
        with tempfile.TemporaryDirectory(prefix="wasm-reference-fifo-") as temporary:
            source = Path(temporary) / "input.elisa"
            os.mkfifo(source)

            with self.assertRaisesRegex(WasmBuildError, "not a regular file"):
                read_flat_source(source)


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
        # Put descendants before parents: ownership must not depend on ps row order.
        snapshot = "102 101 102 30\n101 100 100 20\n200 1 200 99\n100 1 100 10\n"
        with patch(
            "scripts.wasm_export_scan_client._read_process_snapshot",
            return_value=snapshot,
        ):
            self.assertEqual(_process_tree_rss_bytes(process), (10 + 20 + 30) * 1024)

    def test_rss_snapshot_reader_accepts_exact_byte_and_row_limits(self) -> None:
        payload = b"100 1 100 10\n"
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, payload)
            os.close(write_fd)
            write_fd = -1
            stdout = os.fdopen(read_fd, "rb", buffering=0)
            read_fd = -1
            process = SimpleNamespace(
                pid=100,
                stdout=stdout,
                poll=lambda: 0,
                wait=lambda **_kwargs: 0,
            )
            with (
                patch(
                    "scripts.wasm_export_scan_client.MAX_PROCESS_SNAPSHOT_BYTES",
                    len(payload),
                ),
                patch("scripts.wasm_export_scan_client.MAX_PROCESS_SNAPSHOT_ROWS", 1),
                patch("scripts.bounded_process_snapshot.subprocess.Popen", return_value=process) as launch,
                patch("scripts.bounded_process_snapshot._kill_process_group") as kill,
            ):
                self.assertEqual(_read_process_snapshot(), payload.decode("ascii"))
            launch.assert_called_once_with(
                ["/bin/ps", "-axo", "pid=,ppid=,pgid=,rss="],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"LC_ALL": "C"},
                start_new_session=(os.name == "posix"),
                bufsize=0,
            )
            kill.assert_not_called()
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def test_rss_sampler_fails_closed_on_malformed_snapshot(self) -> None:
        process = SimpleNamespace(pid=100)
        with patch(
            "scripts.wasm_export_scan_client._read_process_snapshot",
            return_value="100 1 100 not-a-number\n",
        ):
            self.assertIsNone(_process_tree_rss_bytes(process))

    def test_rss_sampler_fails_closed_on_duplicate_process_ids(self) -> None:
        process = SimpleNamespace(pid=100)
        # Overwriting the first row with a lower RSS value would undercount the
        # scanner unless duplicate identities invalidate the whole snapshot.
        snapshot = "100 1 100 524288\n100 1 100 0\n"
        with patch(
            "scripts.wasm_export_scan_client._read_process_snapshot",
            return_value=snapshot,
        ):
            self.assertIsNone(_process_tree_rss_bytes(process))

    def test_rss_sampler_stops_when_process_snapshot_exceeds_byte_limit(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"123456789")
            os.close(write_fd)
            write_fd = -1
            stdout = os.fdopen(read_fd, "rb", buffering=0)
            read_fd = -1
            process = SimpleNamespace(
                pid=77,
                stdout=stdout,
                poll=lambda: 0,
                wait=lambda **_kwargs: 0,
            )
            with (
                patch("scripts.wasm_export_scan_client.MAX_PROCESS_SNAPSHOT_BYTES", 8),
                patch("scripts.bounded_process_snapshot.subprocess.Popen", return_value=process),
                patch("scripts.bounded_process_snapshot._kill_process_group") as kill,
            ):
                self.assertIsNone(_read_process_snapshot())
            kill.assert_called_once_with(process)
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def test_rss_sampler_stops_when_process_snapshot_exceeds_row_limit(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"1 1 1 1\n2 1 1 1\n")
            os.close(write_fd)
            write_fd = -1
            stdout = os.fdopen(read_fd, "rb", buffering=0)
            read_fd = -1
            process = SimpleNamespace(
                pid=79,
                stdout=stdout,
                poll=lambda: 0,
                wait=lambda **_kwargs: 0,
            )
            with (
                patch("scripts.wasm_export_scan_client.MAX_PROCESS_SNAPSHOT_ROWS", 1),
                patch("scripts.bounded_process_snapshot.subprocess.Popen", return_value=process),
                patch("scripts.bounded_process_snapshot._kill_process_group") as kill,
            ):
                self.assertIsNone(_read_process_snapshot())
            kill.assert_called_once_with(process)
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def test_rss_sampler_stops_when_process_snapshot_read_times_out(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            stdout = os.fdopen(read_fd, "rb", buffering=0)
            read_fd = -1
            process = SimpleNamespace(
                pid=78,
                stdout=stdout,
                poll=lambda: 0,
                wait=lambda **_kwargs: 0,
            )
            with (
                patch(
                    "scripts.wasm_export_scan_client.PROCESS_RSS_QUERY_TIMEOUT_SECONDS",
                    0.001,
                ),
                patch("scripts.bounded_process_snapshot.subprocess.Popen", return_value=process),
                patch("scripts.bounded_process_snapshot._kill_process_group") as kill,
            ):
                self.assertIsNone(_read_process_snapshot())
            kill.assert_called_once_with(process)
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            os.close(write_fd)

    def test_rss_guard_constants_are_bounded(self) -> None:
        self.assertEqual(PROCESS_RSS_LIMIT_BYTES, 512 * 1024 * 1024)
        self.assertEqual(MAX_PROCESS_SNAPSHOT_ROWS, 65536)
        self.assertEqual(MAX_PROCESS_SNAPSHOT_BYTES, 8 * 1024 * 1024)

    def test_rejects_boolean_payload_version(self) -> None:
        with self.assertRaisesRegex(WasmExportScanClientError, "unsupported payload version"):
            _decode_build_payload(self.encode(version=True))

    def test_rejects_raw_invalid_utf8_before_json_field_validation(self) -> None:
        payload = self.encode().replace(b"answer_impl", b"\xff", 1)
        with self.assertRaisesRegex(WasmExportScanClientError, "invalid JSON"):
            _decode_build_payload(payload)

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
        self.assertFalse(args.python_reference_scanner)

    def test_cli_exposes_an_explicit_python_reference_scanner_flag(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
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
                    "--python-reference-scanner",
                ],
            ),
            patch("scripts.wasm_build.build") as build_mock,
        ):
            self.assertEqual(main(), 0)
        args = build_mock.call_args.args[0]
        self.assertTrue(args.python_reference_scanner)

    def test_explicit_python_reference_uses_the_python_scanner(self) -> None:
        source_path = Path("/tmp/input.elisa")
        flattened = "export fn answer() -> i32 = answer_impl\n"
        exports = [{"name": "answer"}]
        args = SimpleNamespace(python_reference_scanner=True)
        with (
            patch("scripts.wasm_build.read_flat_source", return_value=flattened) as read_source,
            patch("scripts.wasm_build.parse_exports", return_value=exports) as parse_source,
        ):
            self.assertEqual(load_export_scan(source_path, args), (flattened, exports))
        read_source.assert_called_once_with(source_path)
        # `component=` arrived with enum exports in component mode (ee50240f); the default
        # path passes it explicitly, so the bare-argument expectation no longer matches.
        parse_source.assert_called_once_with(flattened, component=False)

    def test_missing_scanner_configuration_does_not_fall_back_to_python(self) -> None:
        source_path = Path("/tmp/input.elisa")
        with (
            patch(
                "scripts.wasm_build.read_flat_source",
                side_effect=AssertionError("implicit Python fallback"),
            ) as read_source,
            patch(
                "scripts.wasm_build.parse_exports",
                side_effect=AssertionError("implicit Python fallback"),
            ) as parse_source,
        ):
            with self.assertRaisesRegex(WasmBuildError, "Elisascript export scanner is required"):
                load_export_scan(source_path, SimpleNamespace())
        read_source.assert_not_called()
        parse_source.assert_not_called()

    def test_build_rejects_missing_scanner_before_creating_output_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created" / "module.wasm"
            args = SimpleNamespace(
                source=str(Path(directory) / "input.elisa"),
                output=str(output),
                target="wasm32-unknown-unknown",
                component_types=[],
                wasm_only=False,
                compiler_flags=[],
                compiler="/bin/true",
            )
            with (
                patch(
                    "scripts.wasm_build.read_flat_source",
                    side_effect=AssertionError("implicit Python fallback"),
                ) as read_source,
                patch("scripts.wasm_build.parse_exports") as parse_source,
                patch("scripts.wasm_build.run") as run_command,
            ):
                with self.assertRaisesRegex(WasmBuildError, "Elisascript export scanner is required"):
                    build(args)
            self.assertFalse(output.parent.exists())
            read_source.assert_not_called()
            parse_source.assert_not_called()
            run_command.assert_not_called()

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

    def test_runtime_cache_uses_python_only_for_explicit_reference_mode(self) -> None:
        root = Path("/tmp/elisa-wasm-runtime-cache-test")
        runtime_source = root / "runtime.elisa"
        with patch(
            "scripts.wasm_build.read_flat_source", return_value="flattened"
        ) as python_flatten:
            runtime_cache_path(
                root,
                root / "compiler",
                "wasm32-test",
                runtime_source,
                python_reference_scanner=True,
            )
        python_flatten.assert_called_once_with(runtime_source)

    def test_runtime_cache_requires_explicit_python_oracle_selection(self) -> None:
        root = Path("/tmp/elisa-wasm-runtime-cache-test")
        runtime_source = root / "runtime.elisa"
        with patch(
            "scripts.wasm_build.read_flat_source",
            side_effect=AssertionError("implicit Python fallback"),
        ) as python_flatten:
            with self.assertRaisesRegex(WasmBuildError, "Elisascript export scanner is required"):
                runtime_cache_path(root, root / "compiler", "wasm32-test", runtime_source)
        python_flatten.assert_not_called()


class RuntimeObjectCacheTests(unittest.TestCase):
    def test_runtime_cache_llc_selection_prefers_configured_llvm_bindir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-llc-select-") as temporary:
            root = Path(temporary)
            configured = root / "selected-llvm" / "bin"
            on_path = root / "path-llvm" / "bin"
            configured.mkdir(parents=True)
            on_path.mkdir(parents=True)
            selected_llc = configured / "llc"
            path_llc = on_path / "llc"
            selected_llc.write_bytes(b"selected llc")
            selected_llc.chmod(0o755)
            path_llc.write_bytes(b"path llc")
            path_llc.chmod(0o755)

            with patch.dict(
                os.environ,
                {"ELISA_LLVM_BIN_DIR": str(configured), "PATH": str(on_path)},
                clear=True,
            ):
                self.assertEqual(
                    _resolve_llc_executable(),
                    selected_llc.resolve(),
                    "the runtime cache must fingerprint the compiler-selected llc before PATH",
                )

    def test_runtime_cache_hashes_delegated_compiler_overrides(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-delegated-compiler-") as temporary:
            root = Path(temporary)
            wrapper = root / "compiler-wrapper"
            wrapper.write_bytes(b"wrapper")
            wrapper.chmod(0o755)
            stage1 = root / "bin" / "elisac-stage1"
            stage1.parent.mkdir()
            stage1.write_bytes(b"stage1")
            stage1.chmod(0o755)
            selected = root / "selected-compiler"
            selected.write_bytes(b"compiler-a")
            selected.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            for selector in ("ELISA_STAGE1_BIN", "ELISA_STAGE1_SELF", "ELISA_S0_REAL", "ELISACORE_BIN"):
                with self.subTest(selector=selector):
                    def key() -> Path:
                        with (
                            patch.dict(
                                os.environ,
                                {selector: str(selected), "ELISA_Z3": str(solver)},
                                clear=True,
                            ),
                            patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                            patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                            patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                        ):
                            return runtime_cache_path(
                                root,
                                wrapper,
                                "wasm32-test",
                                runtime_source,
                                python_reference_scanner=True,
                            )

                    first = key()
                    before = selected.stat()
                    selected.write_bytes(b"compiler-b")
                    os.utime(selected, ns=(before.st_atime_ns, before.st_mtime_ns))
                    self.assertNotEqual(
                        first,
                        key(),
                        f"same-path {selector} replacement reused the WASM runtime key",
                    )
                    before = selected.stat()
                    selected.write_bytes(b"compiler-a")
                    os.utime(selected, ns=(before.st_atime_ns, before.st_mtime_ns))

    def test_runtime_cache_key_hashes_compiler_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-key-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler-a")
            compiler.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver-a")
            solver.chmod(0o755)
            llc = root / "llc"
            llc.write_bytes(b"llc-a")
            llc.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            def key() -> Path:
                with (
                    patch.dict(os.environ, {"ELISA_Z3": str(solver)}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=llc.resolve()),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            first = key()
            before = compiler.stat()
            compiler.write_bytes(b"compiler-b")
            os.utime(compiler, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(first, key(), "same-path compiler replacement reused the WASM runtime key")

            compiler.write_bytes(b"compiler-a")
            os.utime(compiler, ns=(before.st_atime_ns, before.st_mtime_ns))
            after_compiler_reset = key()
            before = solver.stat()
            solver.write_bytes(b"solver-b")
            os.utime(solver, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(
                after_compiler_reset,
                key(),
                "same-path SMT solver replacement reused the WASM runtime key",
            )

            solver.write_bytes(b"solver-a")
            os.utime(solver, ns=(before.st_atime_ns, before.st_mtime_ns))
            after_solver_reset = key()
            before = llc.stat()
            llc.write_bytes(b"llc-b")
            os.utime(llc, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(
                after_solver_reset,
                key(),
                "same-path llc replacement reused the WASM runtime key",
            )

            before_permission_change = key()
            compiler.chmod(0o644)
            self.assertNotEqual(
                before_permission_change,
                key(),
                "a non-executable compiler reused a runtime-object cache key",
            )

    def test_runtime_cache_key_hashes_native_object_merger(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-merger-key-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            stage1 = root / "bin" / "elisac-stage1"
            stage1.parent.mkdir()
            stage1.write_bytes(b"stage1")
            stage1.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)
            merger = root / "ld"
            merger.write_bytes(b"merger-a")
            merger.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            def key() -> Path:
                with (
                    patch.dict(
                        os.environ,
                        {"ELISA_Z3": str(solver), "ELISA_LD": str(merger)},
                        clear=True,
                    ),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            first = key()
            before = merger.stat()
            merger.write_bytes(b"merger-b")
            os.utime(merger, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(
                first,
                key(),
                "same-path object-merger replacement reused the WASM runtime key",
            )

    def test_darwin_merger_timeout_is_not_treated_as_the_system_linker(self) -> None:
        with (
            patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True),
            patch("scripts.wasm_build.sys.platform", "darwin"),
            patch("scripts.wasm_build.shutil.which", return_value="/usr/bin/ld"),
            patch(
                "scripts.wasm_build._resolve_executable",
                side_effect=lambda path: Path("/usr/bin/xcrun") if str(path) == "/usr/bin/xcrun" else None,
            ),
            patch(
                "scripts.wasm_build.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="xcrun --find ld", timeout=2),
            ),
        ):
            self.assertEqual(
                _resolve_native_object_merger(),
                (None, False),
                "a timed-out toolchain lookup must be marked unresolved rather than hashing /usr/bin/ld",
            )

    def test_runtime_cache_does_not_assume_path_z3_is_compiler_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-default-solver-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            tools = root / "tools"
            tools.mkdir()
            (tools / "z3").write_bytes(b"path-z3")
            runtime_source = root / "runtime.elisa"

            def key() -> Path:
                with (
                    patch.dict(os.environ, {"PATH": str(tools)}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            self.assertNotEqual(
                key(),
                key(),
                "an unresolved compiler-default SMT solver reused the PATH z3 key",
            )

    def test_runtime_cache_key_frames_source_path_and_flattened_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-key-frame-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)

            def key(source_name: str, flattened: str) -> Path:
                with (
                    patch.dict(os.environ, {"ELISA_Z3": str(solver)}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value=flattened),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        root / source_name,
                        python_reference_scanner=True,
                    )

            first = key("a", "bc")
            second = key("ab", "c")
            self.assertNotEqual(
                first,
                second,
                "ambiguous runtime-path/source concatenation reused one cache key",
            )

    def test_runtime_cache_keys_effective_wasm_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-effective-mode-") as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            stage1 = root / "bin" / "elisac-stage1"
            stage1.write_bytes(b"stage1")
            stage1.chmod(0o755)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            def key(overrides: dict[str, str]) -> Path:
                with (
                    patch.dict(os.environ, {"ELISA_Z3": str(solver), **overrides}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            self.assertEqual(
                key({"ELISA_STAGE1_WASM": "0"}),
                key({}),
                "the wrapper key used an inherited WASM mode it overrides before compilation",
            )

    @unittest.skipIf(os.name == "nt", "Windows ACL trust is not represented by POSIX mode bits")
    def test_runtime_cache_bypasses_writable_ancestor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-root-") as temporary:
            root = Path(temporary) / "shared" / "project"
            root.mkdir(parents=True)
            root.parent.chmod(0o777)
            workspace = root / "workspace"
            workspace.mkdir()
            cached = root / "build" / "wasm-cache" / "runtime.o"
            self.assertFalse(_runtime_cache_directory_ready(cached.parent, root, create=True))

            candidate = workspace / "runtime-cache-candidate.o"

            def compile_candidate(*_args: object) -> None:
                candidate.write_bytes(b"fresh-object")

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=compile_candidate),
                patch(
                    "scripts.wasm_build._publish_runtime_cache",
                    side_effect=AssertionError("untrusted root published an object"),
                ),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")

    def test_runtime_cache_entry_rejects_truncated_and_symlink_payloads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-entry-") as temporary:
            root = Path(temporary)
            cache_dir = root / "build" / "wasm-cache"
            cache_dir.mkdir(parents=True)
            candidate = root / "candidate.o"
            cached = cache_dir / "runtime.o"
            candidate.write_bytes(b"verified-object")
            self.assertTrue(_publish_runtime_cache(candidate, cached))
            self.assertTrue(_runtime_cache_entry_valid(cached))

            cached.write_bytes(b"truncated")
            self.assertFalse(_runtime_cache_entry_valid(cached))

            cached.unlink()
            cached.with_suffix(".o.json").unlink()
            target = root / "outside.o"
            target.write_bytes(b"outside-object")
            cached.symlink_to(target)
            self.assertFalse(_runtime_cache_entry_valid(cached))

    def test_runtime_cache_file_reads_are_nonblocking(self) -> None:
        nonblocking = getattr(os, "O_NONBLOCK", 0)
        if not nonblocking:
            self.skipTest("platform has no nonblocking file-open flag")
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-nonblocking-") as temporary:
            root = Path(temporary)
            cache_dir = root / "build" / "wasm-cache"
            cache_dir.mkdir(parents=True)
            candidate = root / "candidate.o"
            cached = cache_dir / "runtime.o"
            candidate.write_bytes(b"verified-object")
            real_open = os.open
            observed_flags: list[int] = []

            def record_cache_open(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
                if os.fspath(path) in {str(candidate), str(cached), str(cached) + ".json"}:
                    observed_flags.append(flags)
                return real_open(path, flags, *args, **kwargs)

            with patch("scripts.wasm_build.os.open", side_effect=record_cache_open):
                self.assertTrue(_publish_runtime_cache(candidate, cached))
                self.assertTrue(_runtime_cache_entry_valid(cached))

            self.assertGreaterEqual(len(observed_flags), 4)
            self.assertTrue(all(flags & nonblocking for flags in observed_flags))

    def test_failed_manifest_validation_keeps_fresh_candidate_usable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-publish-") as temporary:
            root = Path(temporary)
            cache_dir = root / "build" / "wasm-cache"
            cached = cache_dir / "runtime.o"
            workspace = root / "workspace"
            workspace.mkdir()
            candidate = workspace / "runtime-cache-candidate.o"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=lambda *_args: candidate.write_bytes(b"fresh-object")),
                patch("scripts.wasm_build._runtime_cache_entry_valid", return_value=False),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")

    def test_runtime_cache_hit_rechecks_current_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-hit-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            cache_dir = root / "build" / "wasm-cache"
            cache_dir.mkdir(parents=True)
            cached = cache_dir / "runtime.o"
            original = workspace / "original.o"
            original.write_bytes(b"cached-object")
            self.assertTrue(_publish_runtime_cache(original, cached))

            identity_checks = 0

            def identity_changed() -> bool:
                nonlocal identity_checks
                identity_checks += 1
                return False

            candidate = workspace / "candidate.o"

            def compile_candidate(*_args: object) -> None:
                candidate.write_bytes(b"fresh-object")

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._runtime_cache_directory_ready", return_value=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=compile_candidate),
                patch(
                    "scripts.wasm_build._publish_runtime_cache",
                    side_effect=AssertionError("changed identity was published"),
                ),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                    identity_is_current=identity_changed,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")
            self.assertEqual(identity_checks, 2)

    def test_runtime_cache_bypasses_preload_and_observer_requests(self) -> None:
        for variable, value in (
            ("LD_PRELOAD", "/tmp/requested-side-effect"),
            ("DYLD_INSERT_LIBRARIES", "/tmp/requested-side-effect"),
            ("ELISA_SMT_RLIMIT_LOG", "/tmp/requested-side-effect"),
            ("ELISACORE_CACHE_DEBUG", "/tmp/requested-side-effect"),
            ("ELISACORE_DUMP_MODULE_ON_VERIFY_FAILURE", "/tmp/requested-side-effect"),
            ("ELISACORE_RETAINED_SERVER", ""),
            ("ELISACORE_RETAINED_PROFILE_DIR", "/tmp/requested-side-effect"),
            ("ELISACORE_RETAINED_HEAPPROFILE", "/tmp/requested-side-effect"),
            ("ELISACORE_RETAINED_FAST_PREPARE", "shadow"),
        ):
            with self.subTest(variable=variable), tempfile.TemporaryDirectory(prefix="wasm-runtime-bypass-") as temporary:
                root = Path(temporary)
                workspace = root / "workspace"
                workspace.mkdir()
                candidate = workspace / "runtime-cache-candidate.o"
                cached = root / "build" / "wasm-cache" / "runtime.o"

                def compile_candidate(*_args: object) -> None:
                    candidate.write_bytes(b"fresh-object")

                with (
                    patch.dict(os.environ, {variable: value}, clear=True),
                    patch("scripts.wasm_build._compile_runtime_object", side_effect=compile_candidate),
                    patch(
                        "scripts.wasm_build._publish_runtime_cache",
                        side_effect=AssertionError("observer request used cache"),
                    ),
                ):
                    result = _runtime_object_from_cache(
                        cached,
                        root,
                        workspace,
                        "unused-compiler",
                        "wasm32-test",
                        root / "runtime.elisa",
                        {},
                        label="test runtime compilation",
                        candidate_name=candidate.name,
                    )
                self.assertEqual(result, candidate)
                self.assertEqual(result.read_bytes(), b"fresh-object")

    def test_runtime_cache_keeps_fast_prepare_on_cacheable(self) -> None:
        with patch.dict(os.environ, {"ELISACORE_RETAINED_FAST_PREPARE": "on"}, clear=True):
            self.assertFalse(_runtime_cache_observer_requested())

    def test_runtime_identity_drift_keeps_candidate_out_of_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-drift-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            candidate = workspace / "runtime-cache-candidate.o"
            cached = root / "build" / "wasm-cache" / "runtime.o"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=lambda *_args: candidate.write_bytes(b"fresh-object")),
                patch("scripts.wasm_build._publish_runtime_cache", side_effect=AssertionError("changed identity was published")),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                    identity_is_current=lambda: False,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")


class BoundedStage1CommandTests(unittest.TestCase):
    def test_rss_limit_accepts_the_configured_boundary(self) -> None:
        with patch.dict(os.environ, {"ELISA_STAGE1_MAX_RSS_KB": "2097152"}, clear=True):
            self.assertEqual(bounded_runner.rss_limit_kb(), 2097152)

    def test_rss_limit_fails_closed_for_missing_invalid_and_excessive_values(self) -> None:
        for value, expected_status in (("", 125), ("not-a-number", 125), ("2097153", 2)):
            with self.subTest(value=value):
                with (
                    patch.dict(os.environ, {"ELISA_STAGE1_MAX_RSS_KB": value}, clear=True),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    bounded_runner.rss_limit_kb()
                self.assertEqual(raised.exception.code, expected_status)

    def test_process_snapshot_counts_group_and_descendants_once(self) -> None:
        snapshot = """\
101 1 101 100 S
102 101 101 200 R
103 102 999 300 S
104 1 101 400 Z
105 1 999 500 S
"""
        with (
            patch.object(bounded_runner, "_child_pid", 101),
            patch.object(bounded_runner, "_child_pgid", 101),
            patch.object(
                bounded_runner,
                "read_bounded_process_snapshot",
                return_value=snapshot,
            ) as read_snapshot,
        ):
            self.assertEqual(bounded_runner.process_snapshot(), (1000, 2, True))
        read_snapshot.assert_called_once_with(
            ["-axo", "pid=,ppid=,pgid=,rss=,stat="],
            max_bytes=bounded_runner.MAX_PROCESS_SNAPSHOT_BYTES,
            max_rows=bounded_runner.MAX_PROCESS_ROWS,
            timeout_seconds=bounded_runner.PROCESS_SNAPSHOT_TIMEOUT_SECONDS,
            kill_wait_seconds=bounded_runner.PROCESS_SNAPSHOT_KILL_WAIT_SECONDS,
            chunk_bytes=bounded_runner.PROCESS_SNAPSHOT_CHUNK_BYTES,
        )

    def test_process_snapshot_rejects_incomplete_rows(self) -> None:
        with (
            patch.object(bounded_runner, "_child_pid", 101),
            patch.object(bounded_runner, "_child_pgid", 101),
            patch.object(
                bounded_runner,
                "read_bounded_process_snapshot",
                return_value="101 1 101 100 S\nmalformed\n",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid row"):
                bounded_runner.process_snapshot()

    def test_process_snapshot_rejects_duplicate_process_ids(self) -> None:
        snapshot = "101 1 101 524288 S\n101 1 101 0 S\n"
        with (
            patch.object(bounded_runner, "_child_pid", 101),
            patch.object(bounded_runner, "_child_pgid", 101),
            patch.object(bounded_runner, "read_bounded_process_snapshot", return_value=snapshot),
        ):
            with self.assertRaisesRegex(RuntimeError, "duplicate process id"):
                bounded_runner.process_snapshot()

    def test_process_snapshot_rejects_an_empty_successful_table(self) -> None:
        with patch.object(bounded_runner, "read_bounded_process_snapshot", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "process snapshot was empty"):
                bounded_runner.process_snapshot()

    def test_missing_live_root_does_not_block_wait(self) -> None:
        child = SimpleNamespace(poll=lambda: None, wait=lambda: self.fail("blocking wait"))
        with self.assertRaisesRegex(RuntimeError, "omitted a root that is still running"):
            bounded_runner.child_status_after_snapshot(child, root_live=False)

    def test_stop_group_returns_after_terminated_members_exit(self) -> None:
        with (
            patch.object(bounded_runner, "_child_pgid", 812),
            patch.object(
                bounded_runner,
                "process_snapshot",
                side_effect=((0, 1, True), (0, 0, False)),
            ),
            patch.object(bounded_runner.os, "killpg") as killpg,
            patch.object(bounded_runner.time, "sleep"),
        ):
            bounded_runner.stop_group()
        killpg.assert_called_once_with(812, signal.SIGTERM)

    def test_stop_group_escalates_when_grace_period_expires(self) -> None:
        with (
            patch.object(bounded_runner, "_child_pgid", 913),
            patch.object(bounded_runner.time, "monotonic", side_effect=(0.0, 3.0)),
            patch.object(bounded_runner, "process_snapshot") as snapshot,
            patch.object(bounded_runner.os, "killpg") as killpg,
            patch.object(bounded_runner.time, "sleep"),
        ):
            bounded_runner.stop_group()
        snapshot.assert_not_called()
        self.assertEqual(
            killpg.call_args_list,
            [call(913, signal.SIGTERM), call(913, signal.SIGKILL)],
        )

    def test_entry_point_refuses_to_launch_without_reauthorization(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "argv", ["run_bounded_stage1_command.py", "/bin/true"]),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            bounded_runner.main()
        self.assertEqual(raised.exception.code, 125)

    def test_signal_exit_status_is_normalized(self) -> None:
        self.assertEqual(bounded_runner.normalized_status(42), 42)
        self.assertEqual(bounded_runner.normalized_status(-9), 137)

    def test_opt_in_launcher_and_script_must_be_paired(self) -> None:
        args = SimpleNamespace(export_scan_launcher="/bin/elisac")
        with self.assertRaisesRegex(WasmBuildError, "must be supplied together"):
            load_export_scan(Path("/tmp/input.elisa"), args)


if __name__ == "__main__":
    unittest.main()
