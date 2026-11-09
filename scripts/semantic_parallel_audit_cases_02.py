from pathlib import Path
import re
import unittest

from semantic_parallel_audit_test_support import (TABLE_FIELD_TYPES, analyze, audit, definition, diagnostic_audit)


class SemanticParallelAuditPart2(unittest.TestCase):
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

