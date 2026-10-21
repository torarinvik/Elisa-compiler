#!/usr/bin/env python3
"""Focused soundness and precision checks for the semantic parallel audit."""
from collections import defaultdict
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semantic_parallel_gen as audit
import semantic_parallel_diagnostic_audit as diagnostic_audit


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

    def test_parallel_gate_requires_exact_safe_id_mapping(self):
        gate = audit.parallel_safety_gate_source({1, 4, 9})
        self.assertEqual(audit.parallel_safety_gate_errors(gate, {1, 4, 9}), [])
        self.assertTrue(audit.parallel_safety_gate_errors(gate, {1, 4, 8}))

    def test_parallel_gate_compacts_ranges_without_admitting_gaps(self):
        ids = {0, 1, 2, 4, 6, 7, 8}
        gate = audit.parallel_safety_gate_source(ids)
        self.assertIn("return true if pass_id <= 2", gate)
        self.assertIn("return true if pass_id == 4", gate)
        self.assertIn("return true if pass_id >= 6 and pass_id <= 8", gate)
        conditions = re.findall(r"return true if (.+)", gate)
        for pass_id in [*range(12), 255, 2**32 - 1]:
            admitted = any(eval(condition, {"__builtins__": {}}, {"pass_id": pass_id})
                           for condition in conditions)
            self.assertEqual(admitted, pass_id in ids)
        empty = audit.parallel_safety_gate_source(set())
        self.assertNotIn("return true", empty)

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
        dedented_fallback = runtime.replace(
            "                for offset in 0..<count:\n",
            "            for offset in 0..<count:\n",
        )
        self.assertTrue(audit.parallel_runtime_serial_guard_errors(dedented_fallback))
        sibling_mutation = runtime.replace(
            "                    unsafe_pass <- true\n",
            "                        pass\n"
            "                if unrelated_condition:\n"
            "                    unsafe_pass <- true\n",
        )
        self.assertTrue(audit.parallel_runtime_serial_guard_errors(sibling_mutation))

    def test_generated_parallel_call_uses_explicit_lmut_update(self):
        line = (
            "        table <- par_pass_run(file, flags, table, shared_pool, &pass_scratch_slots[0], 35, 8) "
            "can Global{Read,Write}"
        )
        calls, errors = audit.par_run_calls([line])

        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["start"], calls[0]["count"]), (35, 8))
        self.assertIsNotNone(calls[0]["match"].group(2))
        self.assertIsNotNone(calls[0]["match"].group(3))
        self.assertEqual(audit.normalized_par_run_line(line, calls[0]["match"]), line.replace("&pass_scratch_slots[0]", "loop_view"))

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

    def test_generated_parallel_call_requires_initialized_matching_scratch_slot(self):
        declaration = (
            "        pass_scratch_slots: mutable darray[ParPassScratch[pool]] @pool = "
            "[ParPassScratch[pool]{loop_view: loop_view}]"
        )
        call = (
            "        table <- par_pass_run(file, flags, table, shared_pool, "
            "&pass_scratch_slots[0], 0, 2) can Global{Read,Write}"
        )
        lines = [declaration, call]
        calls, malformed = audit.par_run_calls(lines)
        self.assertEqual(malformed, [])
        self.assertEqual(audit.pipeline_scratch_errors(lines, 0, len(lines), calls), [])

        mismatched = [declaration, call.replace("pass_scratch_slots", "other_slots")]
        mismatched_calls, malformed = audit.par_run_calls(mismatched)
        self.assertEqual(malformed, [])
        self.assertTrue(any(
            "different scratch slot" in error
            for error in audit.pipeline_scratch_errors(mismatched, 0, len(mismatched), mismatched_calls)
        ))

        uninitialized = [call]
        uninitialized_calls, malformed = audit.par_run_calls(uninitialized)
        self.assertEqual(malformed, [])
        self.assertTrue(any(
            "initialize exactly one" in error
            for error in audit.pipeline_scratch_errors(uninitialized, 0, len(uninitialized), uninitialized_calls)
        ))

    def test_typed_view_calls_require_initialized_view(self):
        declaration = "        loop_view: Ast::File = semantic_loop_view(file)"
        call = "        table <- par_pass_run(file, flags, table, shared_pool, loop_view, 0, 2)"
        lines = [declaration, call]
        calls, errors = audit.par_run_calls(lines)
        self.assertEqual(errors, [])
        self.assertEqual(audit.pipeline_scratch_errors(lines, 0, len(lines), calls), [])
        for invalid in [[call], [call, declaration], [declaration, declaration, call],
                        [declaration, call, call.replace("loop_view, 0", "&slots[0], 0")]]:
            invalid_calls, errors = audit.par_run_calls(invalid)
            self.assertEqual(errors, [])
            self.assertTrue(audit.pipeline_scratch_errors(invalid, 0, len(invalid), invalid_calls))

    def test_typed_view_normalization_is_idempotent(self):
        line = "        table <- par_pass_run(file, flags, table, shared_pool, loop_view, 3, 2)"
        calls, errors = audit.par_run_calls([line])
        self.assertEqual(errors, [])
        self.assertEqual(audit.normalized_par_run_line(line, calls[0]["match"]), line)

    def test_emit_uses_typed_view_without_scratch_and_is_idempotent(self):
        from unittest.mock import patch
        lines = ["def check_full_into_pipeline():", "    loop_view: Ast::File = semantic_loop_view(file)",
                 "    table <- check_one(loop_view.top_decls, table)", "    PhaseTimer::minor(\"sem:check_one\")", "    return"]
        run = [{"line": 2, "indent": "    ", "name": "check_one", "args": "loop_view.top_decls, table"}]
        with patch.object(audit, "plan_runs", return_value=(lines, [], [], [run])), patch.object(audit, "pipeline_statements", return_value=(lines, 0, len(lines), [])):
            output, flags, _, _ = audit.emit({})
        self.assertFalse(any("ParPassScratch" in line for line in output))
        self.assertTrue(any("shared_pool, loop_view, 0, 1)" in line for line in output))
        with patch.object(audit, "plan_runs", return_value=(output, flags, [], [])), patch.object(audit, "pipeline_statements", return_value=(output, 0, len(output), [])):
            repeated, _, _, _ = audit.emit({})
        self.assertEqual(repeated, output)

    def test_generated_migration_preserves_other_function_scratch(self):
        from unittest.mock import patch
        outside = "    other_slots: mutable darray[ParPassScratch[pool]] @pool = []"
        inside = "    pass_scratch_slots: mutable darray[ParPassScratch[pool]] @pool = []"
        outside_flags = "    flags: ParPassFlags = ParPassFlags{other: true}"
        lines = ["def other():", outside, outside_flags, "    return", "def check_full_into_pipeline():",
                 "    loop_view: Ast::File = semantic_loop_view(file)", inside,
                 "    table <- par_pass_run(file, flags, table, shared_pool, &pass_scratch_slots[0], 0, 1)", "    return"]
        with patch.object(audit, "plan_runs", return_value=(lines, [], [], [])), patch.object(audit, "pipeline_statements", return_value=(lines, 4, len(lines), [])):
            output, _, _, _ = audit.emit({})
        self.assertIn(outside, output)
        self.assertIn(outside_flags, output)
        self.assertNotIn(inside, output)
        self.assertTrue(any("shared_pool, loop_view, 0, 1)" in line for line in output))

    def test_typed_job_view_requires_field_initialization_and_worker_borrow(self):
        source = ("        struct ParPassJob:\n            loop_view: Ast::File\n"
                  "        def worker():\n            view: Ast::File& = &job.loop_view\n"
                  "        def run():\n            jobs.push(ParPassJob{loop_view: loop_view})\n")
        self.assertEqual(audit.parallel_runtime_view_errors(source), [])
        for broken in [source.replace("loop_view: loop_view", "other: loop_view"),
                       source.replace("loop_view: Ast::File", "other: Ast::File"),
                       source.replace("&job.loop_view", "job.view_bits.cast[Ast::File&]")]:
            self.assertTrue(audit.parallel_runtime_view_errors(broken))

    def test_dispatcher_accepts_single_update_inside_effect_scope(self):
        source = (
            "def par_pass_call(pass_id: u32):\n"
            "    if pass_id == 0:\n"
            "        table <- check_plain(file, table)\n"
            "    elif pass_id == 1:\n"
            "        can Global{Read,Write}:\n"
            "            table <- check_global(file, table)\n"
        )

        records, errors = audit.parse_parallel_dispatch(source)

        self.assertEqual(errors, [])
        self.assertEqual(
            records,
            [
                {"id": 0, "name": "check_plain", "args": "file, table", "condition": None},
                {"id": 1, "name": "check_global", "args": "file, table", "condition": None},
            ],
        )

    def test_dispatcher_rejects_multiple_effect_scope_statements(self):
        source = (
            "def par_pass_call(pass_id: u32):\n"
            "    if pass_id == 0:\n"
            "        can Global{Read,Write}:\n"
            "            before()\n"
            "            table <- check_global(file, table)\n"
        )

        records, errors = audit.parse_parallel_dispatch(source)

        self.assertEqual(records, [])
        self.assertTrue(any("exactly one body statement" in error for error in errors))

    def test_flat_dispatcher_preserves_all_passes_and_rejects_mixed_shapes(self):
        source = "def par_pass_call(pass_id: u32):\n" + ''.join(
            f"    if pass_id == {pid}:\n        table <- check_{pid}(file, table)\n"
            for pid in range(221))
        records, errors = audit.parse_parallel_dispatch(source)
        self.assertEqual(errors, [])
        self.assertEqual([record['id'] for record in records], list(range(221)))
        self.assertEqual([record['name'] for record in records], [f'check_{pid}' for pid in range(221)])
        _records, errors = audit.parse_parallel_dispatch(source.replace('if pass_id == 123:', 'elif pass_id == 123:'))
        self.assertTrue(any('expected if' in error for error in errors))

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
