from pathlib import Path
import re
import unittest

from semantic_parallel_audit_test_support import (TABLE_FIELD_TYPES, analyze, audit, definition, diagnostic_audit)


class SemanticParallelBorrowTests(unittest.TestCase):
    def test_mutable_cast_sources_preserve_boundaries_and_alias_closure(self):
        sources = audit.mutable_cast_source_names("", """
one = shared
two = one
three = Namespace::state
four = π
lookalike = sharedness
""", {}, {}, ("shared", "unused", "Namespace::state", "π"))
        self.assertEqual(sources, {
            "shared", "Namespace::state", "π", "one", "two", "three", "four",
        })

    def test_copy_alias_classification_preserves_qualified_view_lifetimes(self):
        for spelling in ("sview @source", "sview@source", "mutable sview @source"):
            with self.subTest(spelling=spelling):
                self.assertTrue(audit.type_is_copy_value(spelling, {}, {}))
                self.assertTrue(audit.type_may_contain_reference(spelling, {}, {}))
                self.assertFalse(audit.type_may_contain_mutable_alias(spelling, {}, {}))
        aliases = {"Text": ["sview @source"]}
        structs = {"Record": [{"text": "Text", "count": "u32"}]}
        self.assertTrue(audit.type_is_copy_value("Record", aliases, structs))
        self.assertTrue(audit.type_may_contain_reference("Record", aliases, structs))
        self.assertFalse(audit.type_may_contain_mutable_alias("Record", aliases, structs))
        self.assertEqual(
            audit.is_detached_copy_value("Record", aliases, structs),
            audit.is_detached_copy_value("Record", {}, {"Record": [{"text": "sview", "count": "u32"}]}),
        )
        for spelling in ("mutable darray[sview @source]", "mutable sview& @source",
                         "sview @source extra", "sview @source @other", "cstr @source"):
            with self.subTest(unsafe=spelling):
                self.assertFalse(audit.type_is_copy_value(spelling, {}, {}))
                self.assertTrue(audit.type_may_contain_mutable_alias(spelling, {}, {}))

    def test_qualified_view_records_keep_escape_and_mutable_cast_checks(self):
        fields = dict(TABLE_FIELD_TYPES, view_record="ViewRecord")
        structs = {"ViewRecord": [{"name": "sview @source", "ordinal": "usize"}],
                   "SymbolKind": [[]]}
        returned = analyze({"view_record": [definition(
            "table: SymbolTable&",
            "def view_record(table: SymbolTable&) -> ViewRecord:\n"
            "    return table.view_record\n",
        )]}, table_field_types=fields, struct_field_types=structs)
        safe, writes, _ = audit.append_only(returned, "view_record")
        self.assertFalse(safe)
        self.assertTrue(any("returned-table-field-alias" in write for write in writes), writes)
        cast = analyze({
            "mutate_record": [definition(
                "record: ViewRecord",
                "def mutate_record(record: ViewRecord):\n"
                "    name: sview @source = record.name\n"
                "    raw: MutableBytes = name.data.cast[MutableBytes]\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    record: ViewRecord = table.view_record\n"
                "    mutate_record(record)\n",
            )],
        }, table_field_types=fields, struct_field_types=structs,
           type_aliases={"MutableBytes": ["mutable u8&"]})
        safe, writes, _ = audit.append_only(cast, "root")
        self.assertFalse(safe)
        self.assertTrue(any("cast" in write for write in writes), writes)

    def test_diagnostic_ownership_audit_normalizes_region_annotated_views(self):
        self.assertEqual(
            diagnostic_audit.diagnostic_payload_base_type("sview @source"), "sview"
        )
        self.assertEqual(
            diagnostic_audit.diagnostic_payload_base_type("mutable sview @source"),
            "sview",
        )

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

    def test_mutable_alias_type_analysis_allows_views_but_fails_closed_on_storage_and_cycles(self):
        self.assertFalse(audit.type_may_contain_mutable_alias("sview", {}, {}))
        self.assertFalse(audit.type_may_contain_mutable_alias(
            "ViewRecord", {}, {"ViewRecord": [{"name": "sview", "ordinal": "usize"}]}
        ))
        self.assertTrue(audit.type_may_contain_mutable_alias("darray[sview]", {}, {}))
        self.assertTrue(audit.type_may_contain_mutable_alias(
            "AliasA", {"AliasA": ["AliasB"], "AliasB": ["AliasA"]}, {}
        ))
        self.assertTrue(audit.type_may_contain_mutable_alias(
            "RecordA", {}, {"RecordA": [{"next": "RecordB"}], "RecordB": [{"next": "RecordA"}]}
        ))
        # The parser indexes by terminal name across module scopes. A safe alias
        # must not hide a same-named record that owns mutable storage.
        aliases = {"Twin": ["i64"]}
        structs = {"Twin": [{"buffer": "darray[u8]"}]}
        self.assertFalse(audit.is_detached_copy_value("Twin", aliases, structs))

    def test_mutable_call_on_local_copy_of_view_record_does_not_mutate_table_alias(self):
        info = analyze({
            "mutate_record": [definition(
                "record: mutable ViewRecord&",
                "def mutate_record(record: mutable ViewRecord&):\n"
                "    pass\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    record: ViewRecord = table.view_record\n"
                "    mutate_record(&record)\n",
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, view_record="ViewRecord"), struct_field_types={
            "ViewRecord": [{"name": "sview", "ordinal": "usize"}],
            "SymbolKind": [[]],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertTrue(append_only, writes)

    def test_unresolved_cast_from_global_view_is_rejected(self):
        info = analyze({
            "root": [definition(
                "",
                "def root():\n"
                "    raw: UnknownTarget = global_view.data.cast[UnknownTarget]\n",
            )],
        }, globals_={"global_view"})

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertFalse(append_only)
        self.assertTrue(any("cast" in write for write in writes), writes)

    def test_unrelated_unresolved_cast_is_not_attributed_to_reference_parameter(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    scratch: usize = 0\n"
                "    raw: UnknownTarget = scratch.cast[UnknownTarget]\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertTrue(append_only, writes)

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

    def test_immutable_reference_alias_can_be_read_and_forwarded_read_only(self):
        info = analyze({
            "inspect_symbol": [definition(
                "symbol: Symbol&",
                "def inspect_symbol(symbol: Symbol&):\n"
                "    name: sview = symbol.name\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    symbol: Symbol& = &table.symbols[0]\n"
                "    inspect_symbol(symbol)\n",
            )],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertTrue(append_only, writes)
        self.assertNotIn("ref:symbols", writes)

    def test_mutable_reference_alias_is_rejected_at_borrow(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    symbol: mutable Symbol& = &table.symbols[0]\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_immutable_reference_alias_cannot_be_forwarded_mutably(self):
        info = analyze({
            "mutate_symbol": [definition(
                "symbol: mutable Symbol&",
                "def mutate_symbol(symbol: mutable Symbol&):\n"
                "    symbol.name <- \"changed\"\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    symbol: Symbol& = &table.symbols[0]\n"
                "    mutate_symbol(symbol)\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_immutable_reference_alias_cannot_escape(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable) -> Symbol&:\n"
                "    symbol: Symbol& = &table.symbols[0]\n"
                "    return symbol\n",
            )],
        })

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_nested_field_reference_from_immutable_alias_cannot_escape_and_mutate(self):
        info = analyze({
            "state_names": [definition(
                "table: SymbolTable&",
                "def state_names(table: SymbolTable&) -> mutable darray[sview]&:\n"
                "    family: Ast::StateFamily& = &table.state_family_declarations[0]\n"
                "    return &family.states\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    names: mutable darray[sview]& = state_names(table)\n"
                '    names.push("escaped mutation")\n',
            )],
        }, table_field_types=dict(
            TABLE_FIELD_TYPES,
            state_family_declarations="mutable darray[Ast::StateFamily]",
        ), struct_field_types={
            "Ast::StateFamily": [{"states": "mutable darray[sview]"}],
            "SymbolKind": [[]],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertFalse(append_only)
        self.assertTrue(any("returned-table-field-alias" in write for write in writes), writes)

    def test_nested_field_value_from_immutable_alias_is_still_tainted_on_return(self):
        info = analyze({
            "state_names": [definition(
                "table: SymbolTable&",
                "def state_names(table: SymbolTable&) -> mutable darray[sview]:\n"
                "    family: Ast::StateFamily& = &table.state_family_declarations[0]\n"
                "    return family.states\n",
            )],
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    names: mutable darray[sview] = state_names(table)\n"
                '    names.push("possibly shared backing")\n',
            )],
        }, table_field_types=dict(
            TABLE_FIELD_TYPES,
            state_family_declarations="mutable darray[Ast::StateFamily]",
        ), struct_field_types={
            "Ast::StateFamily": [{"states": "mutable darray[sview]"}],
            "SymbolKind": [[]],
        })

        append_only, writes, _ = audit.append_only(info, "root")
        self.assertFalse(append_only)
        self.assertTrue(any("returned-table-field-alias" in write for write in writes), writes)

    def test_scalar_field_from_immutable_alias_can_return_by_value(self):
        info = analyze({
            "state_code": [definition(
                "table: SymbolTable&",
                "def state_code(table: SymbolTable&) -> i32:\n"
                "    family: Ast::StateFamily& = &table.state_family_declarations[0]\n"
                "    return family.code\n",
            )],
        }, table_field_types=dict(
            TABLE_FIELD_TYPES,
            state_family_declarations="mutable darray[Ast::StateFamily]",
        ), struct_field_types={
            "StateFamily": [{"code": "i32", "states": "mutable darray[sview]"}],
            "SymbolKind": [[]],
        })

        append_only, writes, _ = audit.append_only(info, "state_code")
        self.assertTrue(append_only, writes)

    def test_sview_return_from_table_field_is_rejected_as_borrowed_storage(self):
        info = analyze({
            "name_view": [definition(
                "table: SymbolTable&",
                "def name_view(table: SymbolTable&) -> sview:\n"
                "    return table.current_name\n",
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, current_name="sview"))

        append_only, writes, _ = audit.append_only(info, "name_view")
        self.assertFalse(append_only)
        self.assertTrue(any("returned-table-field-alias" in write for write in writes), writes)

    def test_copyable_struct_with_sview_field_is_still_borrowed(self):
        info = analyze({
            "view_record": [definition(
                "table: SymbolTable&",
                "def view_record(table: SymbolTable&) -> ViewRecord:\n"
                "    return table.view_record\n",
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, view_record="ViewRecord"), struct_field_types={
            "ViewRecord": [{"name": "sview", "ordinal": "usize"}],
            "SymbolKind": [[]],
        })

        append_only, writes, _ = audit.append_only(info, "view_record")
        self.assertFalse(append_only)
        self.assertTrue(any("returned-table-field-alias" in write for write in writes), writes)

    def test_reference_in_nested_block_return_arm_remains_rejected(self):
        info = analyze({
            "choose": [definition(
                "table: SymbolTable&, enabled: bool",
                'def choose(table: SymbolTable&, enabled: bool) -> sview:\n'
                '    return if enabled:\n'
                '        if table.current_name == "x":\n'
                '            table.current_name\n'
                '        else:\n'
                '            "fallback"\n'
                '    else:\n'
                '        "other"\n',
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, current_name="sview"))

        append_only, writes, _ = audit.append_only(info, "choose")
        self.assertFalse(append_only)

    def test_reference_in_postfix_return_value_arm_remains_rejected(self):
        info = analyze({
            "choose": [definition(
                "table: SymbolTable&, enabled: bool",
                'def choose(table: SymbolTable&, enabled: bool) -> sview:\n'
                '    return table.current_name if enabled else "fallback"\n',
            )],
        }, table_field_types=dict(TABLE_FIELD_TYPES, current_name="sview"))

        append_only, writes, _ = audit.append_only(info, "choose")
        self.assertFalse(append_only)
        self.assertIn("returned-table-field-alias", writes)

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

    def test_grouped_address_cast_of_table_field_is_rejected(self):
        fields = dict(TABLE_FIELD_TYPES, current_name="sview")
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    bits: usize = (&table.current_name).cast[usize]\n",
            )],
        }, table_field_types=fields)

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_direct_table_view_data_cast_is_rejected(self):
        fields = dict(TABLE_FIELD_TYPES, current_name="sview")
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    bits: usize = table.current_name.data.cast[usize]\n",
            )],
        }, table_field_types=fields)

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_grouped_table_view_data_cast_is_rejected(self):
        fields = dict(TABLE_FIELD_TYPES, current_name="sview")
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    bits: usize = (table.current_name.data).cast[usize]\n",
            )],
        }, table_field_types=fields)

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_grouped_address_cast_of_copied_table_view_is_rejected(self):
        fields = dict(TABLE_FIELD_TYPES, current_name="sview")
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    name: sview = table.current_name\n"
                "    bits: usize = (&name.data).cast[usize]\n",
            )],
        }, table_field_types=fields)

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_direct_data_cast_of_copied_table_view_is_rejected(self):
        fields = dict(TABLE_FIELD_TYPES, current_name="sview")
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    name: sview = table.current_name\n"
                "    bits: usize = name.data.cast[usize]\n",
            )],
        }, table_field_types=fields)

        self.assertFalse(audit.append_only(info, "root")[0])

    def test_read_only_view_length_of_table_field_is_allowed(self):
        info = analyze({
            "root": [definition(
                "table: lmut SymbolTable",
                "def root(table: lmut SymbolTable):\n"
                "    length: usize = table.symbol_name.len\n",
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
