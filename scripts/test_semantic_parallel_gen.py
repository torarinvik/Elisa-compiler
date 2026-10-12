#!/usr/bin/env python3
"""Focused soundness and precision checks for the semantic parallel audit."""
from collections import defaultdict
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semantic_parallel_gen as audit


TABLE_FIELD_TYPES = {
    "diagnostics": "mutable darray[Diagnostic]",
    "symbols": "mutable darray[Symbol]",
    "duplicates": "mutable u32",
    "pointer_bits": "uintptr",
}


def definition(params, body, external=False):
    lines = body.splitlines(keepends=True)
    return_type = ""
    if lines:
        match = re.search(r"\)\s*->\s*([^:\n]+)\s*:", lines[0])
        if match:
            return_type = match.group(1).strip()
    return {
        "params": params,
        "return_type": return_type,
        "body": lines,
        "external": external,
    }


def analyze(
    definitions, globals_=(), table_field_types=None, struct_field_types=None, type_aliases=None,
    enum_variants=None,
):
    defs = defaultdict(list)
    defs.update(definitions)
    return audit.analyze(
        defs, set(globals_), set(), type_aliases or {}, table_field_types or TABLE_FIELD_TYPES,
        struct_field_types or {"SymbolKind": [[]]}, enum_variants or {},
    )


class SemanticParallelAuditTest(unittest.TestCase):
    def test_method_receiver_stops_at_nested_index_boundary(self):
        self.assertEqual(
            list(audit.call_sites("table.symbols[cur.usize()]")),
            [("usize", "cur", [])],
        )
        self.assertEqual(
            list(audit.call_sites("(cur).usize()")),
            [("usize", "(cur)", [])],
        )

    def test_known_append_only_helper_accepts_whole_table_forwarding(self):
        info = analyze({
            "append_diagnostic": [definition(
                "table: mutable SymbolTable",
                "def append_diagnostic(table: mutable SymbolTable):\n"
                "    table.diagnostics <- table.diagnostics.push(Diagnostic{})\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    append_diagnostic(table)\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_unknown_and_external_helpers_fail_closed_for_whole_table(self):
        unknown_info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    unknown_helper(table)\n",
            )],
        })
        external_info = analyze({
            "external_helper": [definition("", "", external=True)],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    external_helper(table)\n",
            )],
        })

        unknown_ok, unknown_writes, _ = audit.append_only(unknown_info, "root")
        external_ok, external_writes, _ = audit.append_only(external_info, "root")
        self.assertFalse(unknown_ok)
        self.assertTrue(any("whole-table-argument:unknown_helper" in write for write in unknown_writes))
        self.assertFalse(external_ok)
        self.assertTrue(any("whole-table-argument:external_helper" in write for write in external_writes))

    def test_unknown_zero_argument_call_fails_closed(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    unknown_side_effect()\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_unknown_zero_argument_call_in_helper_fails_closed(self):
        info = analyze({
            "unknown_helper": [definition(
                "",
                "def unknown_helper():\n"
                "    unknown_side_effect()\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    unknown_helper()\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_unknown_call_with_arguments_in_helper_fails_closed(self):
        info = analyze({
            "unknown_helper": [definition(
                "",
                "def unknown_helper():\n"
                "    unknown_side_effect(1)\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    unknown_helper()\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_unknown_receiver_method_in_helper_fails_closed(self):
        info = analyze({
            "unknown_helper": [definition(
                "object: LocalObject",
                "def unknown_helper(object: LocalObject):\n"
                "    object.mutate_global_state(1)\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable, object: LocalObject",
                "def root(table: lmut SymbolTable, object: LocalObject):\n"
                "    unknown_helper(object)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_nested_enum_pattern_is_not_an_unknown_receiver_method(self):
        info = analyze(
            {
                "root": [definition(
                    "",
                    "def root():\n"
                    "    match value:\n"
                    "        Stmt.Assign(Expr.Ident(name, _), _, _, _): pass\n",
                )],
            },
            enum_variants={"Stmt": {"Assign"}, "Expr": {"Ident"}},
        )

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_known_pure_free_intrinsic_is_allowed(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                'def root(table: lmut SymbolTable):\n    name: sview = sview("symbol")\n',
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_copy_value_type_resolution_handles_deep_alias_chains(self):
        aliases = {"Alias0": ["sview"]}
        for index in range(1, 1200):
            aliases[f"Alias{index}"] = [f"Alias{index - 1}"]
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    current: Alias1199 = table.current_module\n",
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, current_module="sview"), type_aliases=aliases)

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_known_source_helper_mutating_table_field_is_rejected(self):
        info = analyze({
            "mutate_table": [definition(
                "table: lmut SymbolTable",
                "def mutate_table(table: lmut SymbolTable):\n"
                '    table.symbols <- table.symbols.push(Symbol{name: "x"})\n',
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    mutate_table(table)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_explicit_table_field_reference_to_mutable_helper_is_rejected(self):
        info = analyze({
            "mutate_symbols": [definition(
                "values: mutable darray[Symbol]&",
                "def mutate_symbols(values: mutable darray[Symbol]&):\n"
                "    pass\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    mutate_symbols(&table.symbols)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_mutable_reference_alias_of_table_field_is_rejected(self):
        info = analyze({
            "mutate_symbols": [definition(
                "values: mutable darray[Symbol]&",
                "def mutate_symbols(values: mutable darray[Symbol]&):\n"
                "    pass\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    values: mutable darray[Symbol]& = table.symbols\n"
                "    mutate_symbols(values)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_table_derived_receiver_from_known_helper_is_rejected(self):
        info = analyze({
            "view_from": [definition(
                "table: SymbolTable&",
                "def view_from(table: SymbolTable&) -> darray[Symbol]:\n"
                "    return table.symbols\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    view_from(table).push(1)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

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

    def test_builtin_push_through_mutable_struct_reference_accepts_scalar_copy(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable, state: mutable GlobalAuthority&",
                "def root(table: lmut SymbolTable, state: mutable GlobalAuthority&):\n"
                "    state.function_scopes.push(table.duplicates)\n",
            )],
        }, struct_field_types={
            "GlobalAuthority": [{"function_scopes": "mutable darray[usize]"}],
            "SymbolKind": [[]],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_call_receiver_stops_at_unfinished_index_and_keeps_grouped_casts(self):
        calls = list(audit.call_sites(
            "table.symbols[cur.usize()]\n(cur).usize()\n"
        ))

        self.assertEqual(calls[0], ("usize", "cur", []))
        self.assertEqual(calls[1], ("usize", "(cur)", []))

    def test_string_contents_are_hidden_without_erasing_the_argument(self):
        calls = list(audit.call_sites(audit.mask_string_literals(
            'getenv("unknown_side_effect()")'
        )))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "getenv")
        self.assertIsNone(calls[0][1])
        self.assertEqual(len(calls[0][2]), 1)

    def test_fstring_interpolation_calls_remain_visible_to_the_audit(self):
        masked = audit.mask_string_literals(
            'rendered: sview = f"literal unknown_side_effect() {mutate(table)}"'
        )
        calls = list(audit.call_sites(masked))
        self.assertIn(("mutate", None, ["table"]), calls)
        self.assertNotIn("unknown_side_effect", [call[0] for call in calls])

    def test_fstring_interpolation_helper_effect_reaches_the_root(self):
        info = analyze({
            "mutate": [definition(
                "table: mutable SymbolTable",
                "def mutate(table: mutable SymbolTable) -> usize:\n"
                "    table.duplicates <- table.duplicates + 1\n"
                "    return 1\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                'def root(table: lmut SymbolTable):\n'
                '    rendered: sview = f"{mutate(table)}"\n',
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_fstring_interpolation_calls_remain_visible_to_the_audit(self):
        masked = audit.mask_string_literals(
            'rendered: sview = f"literal unknown_side_effect() {mutate(table)}"'
        )
        calls = list(audit.call_sites(masked))
        self.assertIn(("mutate", None, ["table"]), calls)
        self.assertNotIn("unknown_side_effect", [call[0] for call in calls])

    def test_fstring_interpolation_helper_effect_reaches_the_root(self):
        info = analyze({
            "mutate": [definition(
                "table: mutable SymbolTable",
                "def mutate(table: mutable SymbolTable) -> usize:\n"
                "    table.duplicates <- table.duplicates + 1\n"
                "    return 1\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                'def root(table: lmut SymbolTable):\n'
                '    rendered: sview = f"{mutate(table)}"\n',
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_raw_address_integer_copy_remains_tainted(self):
        info = analyze({
            "mutate_address": [definition(
                "value: mutable uintptr&",
                "def mutate_address(value: mutable uintptr&):\n"
                "    pass\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    bits: uintptr = table.pointer_bits\n"
                "    mutate_address(bits)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_read_only_view_length_of_table_field_is_allowed(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    length: usize = sview_len(table.symbol_name)\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_user_scalar_cast_from_table_field_propagates_global_effect(self):
        fields = dict(TABLE_FIELD_TYPES, mode="Mode")
        info = analyze({
            "__cast__": [definition(
                "value: Mode",
                "def __cast__(value: Mode) -> u64:\n"
                "    global_calls <- global_calls + 1\n"
                "    return 1\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    converted: u64 = table.mode.u64()\n",
            )],
        }, globals_={"global_calls"}, table_field_types=fields)

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_builtin_scalar_cast_hook_is_not_assumed_pure(self):
        info = analyze({
            "__cast__": [definition(
                "value: u32",
                "def __cast__(value: u32) -> usize:\n"
                "    global_calls <- global_calls + 1\n"
                "    return 0\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    converted: usize = table.duplicates.usize()\n",
            )],
        }, globals_={"global_calls"})

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_unrelated_custom_cast_does_not_taint_builtin_scalar_cast(self):
        info = analyze({
            "__cast__": [
                definition(
                    "value: u64",
                    "def __cast__(value: u64) -> usize:\n"
                    "    global_calls <- global_calls + 1\n"
                    "    return 0\n",
                ),
                definition(
                    "value: u32",
                    "def __cast__(value: u32) -> u64:\n"
                    "    global_calls <- global_calls + 1\n"
                    "    return 0\n",
                ),
            ],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    converted: usize = table.duplicates.usize()\n",
            )],
        }, globals_={"global_calls"})

        self.assertTrue(audit.append_only(info, "root")[0])

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


if __name__ == "__main__":
    unittest.main()
