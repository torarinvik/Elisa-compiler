from __future__ import annotations

from wasm_build_test_support import *


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

