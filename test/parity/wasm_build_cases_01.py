from __future__ import annotations

from wasm_build_test_support import *


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

