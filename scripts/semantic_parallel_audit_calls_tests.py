from pathlib import Path
import re
import unittest

from semantic_parallel_audit_test_support import (TABLE_FIELD_TYPES, analyze, audit, definition, diagnostic_audit)


class SemanticParallelCallsTests(unittest.TestCase):
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

    def test_ghost_helper_in_contract_is_analyzed_as_a_known_callee(self):
        ghost_header = "ghost def count_from(names: darray[sview]&, index: usize) -> i64:"
        match = audit.DEF_RE.match(ghost_header)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(2), "count_from")
        self.assertEqual(match.group(3), "names: darray[sview]&, index: usize")

        info = analyze({
            "count_from": [definition(
                "names: darray[sview]&, index: usize",
                "ghost def count_from(names: darray[sview]&, index: usize) -> i64:\n"
                "    return 0 if index >= names.count\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    ensure count_from([], 0) == 0\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertTrue(append_only, writes)

    def test_unknown_call_in_ghost_helper_still_fails_closed(self):
        info = analyze({
            "count_from": [definition(
                "names: darray[sview]&",
                "ghost def count_from(names: darray[sview]&):\n"
                "    unknown_side_effect()\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    ensure count_from([]) == 0\n",
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

    def test_unknown_receiver_method_name_collision_fails_closed(self):
        info = analyze({
            # This free function is unrelated to ExternalObject.inspect.  Its
            # name alone must not make the receiver call look source-resolved.
            "inspect": [definition(
                "value: i32",
                "def inspect(value: i32):\n"
                "    return\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable, object: ExternalObject",
                "def root(table: lmut SymbolTable, object: ExternalObject):\n"
                "    object.inspect()\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])
        self.assertNotIn("inspect", info["root"][2])

    def test_receiver_method_with_matching_source_first_formal_is_resolved(self):
        info = analyze({
            "inspect": [definition(
                "object: LocalObject&",
                "def inspect(object: LocalObject&):\n"
                "    return\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable, object: LocalObject",
                "def root(table: lmut SymbolTable, object: LocalObject):\n"
                "    object.inspect()\n",
            )],
        })

        self.assertTrue(audit.append_only(info, "root")[0])

    def test_ambiguous_receiver_alias_does_not_prove_source_dispatch(self):
        info = analyze({
            "inspect": [definition(
                "object: Twin",
                "def inspect(object: Twin):\n"
                "    return\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable, object: Twin",
                "def root(table: lmut SymbolTable, object: Twin):\n"
                "    object.inspect()\n",
            )],
        }, type_aliases={"Twin": ["LocalObject", "OtherObject"]})

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertFalse(append_only)
        self.assertIn("unknown-receiver-call:inspect", writes)
        self.assertNotIn("inspect", info["root"][2])

    def test_unknown_numeric_receiver_conversion_fails_closed(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable, object: ExternalObject",
                "def root(table: lmut SymbolTable, object: ExternalObject):\n"
                "    object.i64()\n",
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

    def test_copy_value_type_resolution_fails_closed_on_unknown_descendants(self):
        self.assertFalse(audit.type_is_copy_value(
            "AliasRoot",
            {"AliasRoot": ["AliasLeaf"], "AliasLeaf": ["UnknownType"]},
            {},
        ))
        self.assertFalse(audit.type_is_copy_value(
            "StructRoot",
            {},
            {"StructRoot": [{"field": "UnknownType"}]},
        ))

    def test_mutable_helper_raw_cast_from_copied_view_record_stays_rejected(self):
        info = analyze({
            "mutate_record": [definition(
                "record: ViewRecord",
                "def mutate_record(record: ViewRecord):\n"
                "    name: sview = record.name\n"
                "    raw: MutableBytes = name.data.cast[MutableBytes]\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    record: ViewRecord = table.view_record\n"
                "    mutate_record(record)\n",
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, view_record="ViewRecord"), struct_field_types={
            "ViewRecord": [{"name": "sview", "ordinal": "usize"}],
            "SymbolKind": [[]],
        }, type_aliases={"MutableBytes": ["MutableByteAlias"], "MutableByteAlias": ["mutable u8&"]})

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertFalse(append_only)
        self.assertTrue(any("cast" in write for write in writes), writes)

    def test_mutable_cast_through_table_getter_receiver_is_rejected(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    raw: UnknownTarget = table.get_view(key).data.cast[UnknownTarget]\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertFalse(append_only)
        self.assertTrue(any("cast" in write for write in writes), writes)

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

    def test_call_receiver_stops_at_unfinished_index_and_keeps_grouped_casts(self):
        calls = list(audit.call_sites(
            "table.symbols[cur.usize()]\n(cur).usize()\n"
        ))

        self.assertEqual(calls[0], ("usize", "cur", []))
        self.assertEqual(calls[1], ("usize", "(cur)", []))

    def test_fstring_interpolation_calls_remain_visible_to_the_audit(self):
        masked = audit.mask_string_literals(
            'rendered: sview = f"literal unknown_side_effect() {1}{mutate(table)}"'
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
                '    rendered: sview = f"{1}{mutate(table)}"\n',
            )],
        })

        self.assertIn("mutate", info["root"][2])
        self.assertFalse(audit.append_only(info, "root")[0])
