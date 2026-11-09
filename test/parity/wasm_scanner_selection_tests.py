from __future__ import annotations

from wasm_build_test_support import *


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

