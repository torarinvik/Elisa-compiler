from pathlib import Path
import re
import unittest

from semantic_parallel_audit_test_support import (TABLE_FIELD_TYPES, analyze, audit, definition, diagnostic_audit)


class SemanticParallelFlowTests(unittest.TestCase):
    def test_local_type_cache_keeps_source_and_schema_changes_separate(self):
        source = "def probe(value: Record):\n    local: Other = value\n"
        self.assertEqual(audit.local_path_expression_type("value.field", source, {
            "Record": [{"field": "sview"}],
        }), "sview")
        self.assertEqual(audit.local_path_expression_type("value.field", source, {
            "Record": [{"field": "mutable darray[sview]"}],
        }), "mutable darray[sview]")
        changed = source.replace("value: Record", "value: Changed")
        self.assertEqual(audit.local_path_expression_type("value.field", changed, {
            "Changed": [{"field": "u32"}],
        }), "u32")
        self.assertEqual(audit.local_path_expression_type("local", source, {}), "Other")

    def test_parallel_runtime_gate_must_precede_worker_submission(self):
        runtime = (
            "        def par_pass_run[@pool](first: u32, count: u32) -> void:\n"
            "            unsafe_pass: mutable bool = false\n"
            "            for offset in 0..<count:\n"
            "                if not par_pass_is_append_only(first + offset):\n"
            "                    unsafe_pass <- true\n"
            "            if count < 2 or shared_pool.handle == null or unsafe_pass:\n"
            "                for offset in 0..<count:\n"
            "                    table <- par_pass_call[destination](first + offset, file, &loop_view, flags, table)\n"
            "                return\n"
            "            region par_pass_jobs_region:\n"
            "                jobs: mutable darray[ParPassJob] @par_pass_jobs_region = []\n"
            "                nursery on(shared_pool):\n"
            "                    submit par_pass_worker(ticket)\n"
        )
        self.assertEqual(audit.parallel_runtime_serial_guard_errors(runtime), [])
        missing_move_return = runtime.replace("                return\n", "                pass\n")
        self.assertTrue(audit.parallel_runtime_serial_guard_errors(missing_move_return))
        immutable_guard = runtime.replace(
            "unsafe_pass: mutable bool = false",
            "unsafe_pass: bool = false",
        )
        self.assertTrue(audit.parallel_runtime_serial_guard_errors(immutable_guard))
        bypassed = runtime.replace("or unsafe_pass:", "or false:")
        self.assertTrue(audit.parallel_runtime_serial_guard_errors(bypassed))
        late_gate = runtime.replace(
            "                if not par_pass_is_append_only(first + offset):\n"
            "                    unsafe_pass <- true\n",
            "",
        ).replace(
            "                nursery on(shared_pool):\n",
            "                nursery on(shared_pool):\n"
            "                    if not par_pass_is_append_only(first + offset):\n"
            "                        unsafe_pass <- true\n",
        )
        self.assertTrue(audit.parallel_runtime_serial_guard_errors(late_gate))

    def test_bare_parallel_call_normalizes_to_explicit_lmut_update(self):
        line = (
            "        par_pass_run(file, flags, table, shared_pool, &pass_scratch_slots[0], 35, 8) "
            "can Global{Read,Write}"
        )
        calls, errors = audit.par_run_calls([line])

        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["start"], calls[0]["count"]), (35, 8))
        self.assertIsNone(calls[0]["match"].group(2))
        self.assertIsNotNone(calls[0]["match"].group(3))
        self.assertEqual(
            audit.normalized_par_run_line(line, calls[0]["match"]),
            "        table <- par_pass_run(file, flags, table, shared_pool, loop_view, 35, 8) "
            "can Global{Read,Write}",
        )

    def test_static_type_qualified_source_call_stays_in_call_graph(self):
        info = analyze({
            "inspect": [definition(
                "value: i32",
                "def inspect(value: i32):\n"
                "    return\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable, value: i32",
                "def root(table: lmut SymbolTable, value: i32):\n"
                "    Owner.inspect(value)\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])
        self.assertIn("inspect", info["root"][2])

    def test_guarded_match_variant_is_not_an_ast_construction(self):
        info = analyze({
            "root": [definition(
                "",
                "def root():\n"
                "    match expression:\n"
                "        Expr.Field(object, field, _) if field == \"count\": pass\n",
            )],
        }, enum_variants={"Expr": {"Field"}})

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_read_only_table_field_iteration_is_not_a_region_write(self):
        info = analyze({
            "root": [definition(
                "table: SymbolTable&",
                "def root(table: SymbolTable&):\n"
                "    for symbol in table.symbols:\n"
                "        pass\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertTrue(append_only, writes)

    def test_computed_scalar_return_from_table_field_stays_append_only(self):
        info = analyze({
            "next_duplicate_count": [definition(
                "table: SymbolTable&",
                "def next_duplicate_count(table: SymbolTable&) -> u32:\n"
                "    return table.duplicates + 1\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "next_duplicate_count")
        self.assertTrue(append_only, writes)

    def test_conditional_scalar_return_from_table_field_stays_append_only(self):
        info = analyze({
            "selected_duplicate_count": [definition(
                "table: SymbolTable&, enabled: bool",
                "def selected_duplicate_count(table: SymbolTable&, enabled: bool) -> u32:\n"
                "    return if enabled:\n"
                "        table.duplicates\n"
                "    else:\n"
                "        0\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "selected_duplicate_count")
        self.assertTrue(append_only, writes)

    def test_table_field_used_only_in_block_return_predicate_stays_append_only(self):
        info = analyze({
            "choose": [definition(
                "table: SymbolTable&, enabled: bool",
                'def choose(table: SymbolTable&, enabled: bool) -> u32:\n'
                '    return if table.current_name == "x":\n'
                '        1\n'
                '    else:\n'
                '        0\n',
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, current_name="sview"))

        append_only, writes, _ = audit.append_only(info, "choose")
        self.assertTrue(append_only, writes)

    def test_table_field_used_only_in_nested_block_return_predicate_stays_append_only(self):
        info = analyze({
            "choose": [definition(
                "table: SymbolTable&, enabled: bool",
                'def choose(table: SymbolTable&, enabled: bool) -> u32:\n'
                '    return if enabled:\n'
                '        if table.current_name == "x":\n'
                '            1\n'
                '        else:\n'
                '            0\n'
                '    else:\n'
                '        2\n',
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, current_name="sview"))

        append_only, writes, _ = audit.append_only(info, "choose")
        self.assertTrue(append_only, writes)

    def test_table_field_used_only_in_postfix_return_predicate_stays_append_only(self):
        info = analyze({
            "choose": [definition(
                "table: SymbolTable&, enabled: bool",
                'def choose(table: SymbolTable&, enabled: bool) -> u32:\n'
                '    return 1 if table.current_name == "x" else 0\n',
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, current_name="sview"))

        append_only, writes, _ = audit.append_only(info, "choose")
        self.assertTrue(append_only, writes)

    def test_newline_return_value_block_cannot_escape_table_field(self):
        info = analyze({
            "expose": [definition(
                "table: SymbolTable&",
                "def expose(table: SymbolTable&) -> mutable darray[Symbol]:\n"
                "    return\n"
                "        table.symbols\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    view: mutable darray[Symbol] = expose(table)\n"
                '    view.push(Symbol{name: "x"})\n',
            )],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertFalse(append_only)
        self.assertTrue(any("returned-table-field-alias" in write for write in writes), writes)

    def test_multiline_parenthesized_return_cannot_escape_table_field(self):
        info = analyze({
            "expose": [definition(
                "table: SymbolTable&",
                "def expose(table: SymbolTable&) -> mutable darray[Symbol]:\n"
                "    return (\n"
                "        table.symbols\n"
                "    )\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "expose")
        self.assertFalse(append_only)
        self.assertTrue(any("returned-table-field-alias" in write for write in writes), writes)

    def test_multiline_conditional_return_cannot_escape_table_field(self):
        info = analyze({
            "expose": [definition(
                "table: SymbolTable&, enabled: bool",
                "def expose(table: SymbolTable&, enabled: bool) -> mutable darray[Symbol]:\n"
                "    return if enabled:\n"
                "        table.symbols\n"
                "    else:\n"
                "        []\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "expose")
        self.assertFalse(append_only)
        self.assertIn("returned-table-field-alias", writes)

    def test_table_field_returned_and_stored_then_mutated_is_rejected(self):
        info = analyze({
            "view_from": [definition(
                "table: SymbolTable&",
                "def view_from(table: SymbolTable&) -> mutable darray[Symbol]&:\n"
                "    return table.symbols\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    view: mutable darray[Symbol]& = view_from(table)\n"
                "    view.push(Symbol{name: \\\"x\\\"})\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_table_field_lookup_then_mutation_is_rejected(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    table.symbols.get(0).push(1)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_scalar_field_copy_is_a_local_mutable_scratch_value(self):
        info = analyze({
            "mutate_scratch": [definition(
                "value: mutable u32&",
                "def mutate_scratch(value: mutable u32&):\n"
                "    pass\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    scratch: u32 = table.duplicates\n"
                "    mutate_scratch(scratch)\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_builtin_darray_push_accepts_a_scalar_field_copy(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    values: mutable darray[u32] = []\n"
                "    values.push(table.duplicates)\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_string_contents_are_hidden_without_erasing_the_argument(self):
        calls = list(audit.call_sites(audit.mask_string_literals(
            'getenv("unknown_side_effect()")'
        )))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "getenv")
        self.assertIsNone(calls[0][1])
        self.assertEqual(len(calls[0][2]), 1)

    def test_mutable_push_item_parameter_keeps_table_scalar_tainted(self):
        info = analyze({
            "push": [definition(
                "values: mutable darray[u32]&, item: mutable u32&",
                "def push(values: mutable darray[u32]&, item: mutable u32&):\n"
                "    pass\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    values: mutable darray[u32] = []\n"
                "    values.push(table.duplicates)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_return_and_boolean_operators_are_not_calls(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    return (table.duplicates > 0 and (not (table.duplicates == 0)))\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_returned_container_count_is_a_scalar_copy(self):
        info = analyze({
            "count_symbols": [definition(
                "table: SymbolTable&",
                "def count_symbols(table: SymbolTable&) -> usize:\n"
                "    return table.symbols.count\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "count_symbols")[0])

    def test_diagnostic_append_payload_read_is_allowed(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                'def root(table: lmut SymbolTable):\n'
                '    table.diagnostics <- table.diagnostics.push(Diagnostic{name: table.symbols[0].name})\n',
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_diagnostic_replacement_is_not_append_only(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    table.diagnostics <- []\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_chained_diagnostic_push_then_mutation_is_not_append_only(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    table.diagnostics <- table.diagnostics.push(Diagnostic{}).clear()\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])
