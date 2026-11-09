from pathlib import Path
import re
import unittest

from semantic_parallel_audit_test_support import (TABLE_FIELD_TYPES, analyze, audit, definition, diagnostic_audit)


class SemanticParallelAuditPart1(unittest.TestCase):
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

    def test_split_batches_preserves_unsafe_boundaries_and_order(self):
        safe = {0, 1, 3, 4, 5, 7}
        batches = list(audit.split_parallel_range(0, 9, safe))
        self.assertEqual(batches, [(0, 2), (2, 1), (3, 3), (6, 1), (7, 1), (8, 1)])
        self.assertEqual([i for first, count in batches for i in range(first, first + count)], list(range(9)))
        for first, count in batches:
            self.assertTrue(count == 1 or all(i in safe for i in range(first, first + count)))
            self.assertEqual(list(audit.split_parallel_range(first, count, safe)), [(first, count)])
        self.assertEqual(list(audit.split_parallel_range(3, 0, safe)), [])

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

    def test_dispatcher_callers_grant_the_declared_unsafe_effects(self):
        source = (audit.SRC + "/semantic/semantic_parallel.elisa")
        passes = (audit.SRC + "/semantic/semantic_parallel_passes.elisa")
        with open(source, encoding="utf-8") as f:
            runtime = f.read()
        with open(passes, encoding="utf-8") as f:
            dispatcher = f.read()
        self.assertEqual(audit.parallel_runtime_lmut_errors(runtime, dispatcher), [])
        missing_grant = runtime.replace(
            "can Global{Read,Write}, Unsafe{PointerArithmetic,PointerCast,RawExtern}",
            "can Global{Read,Write}",
            1,
        )
        self.assertTrue(audit.parallel_runtime_lmut_errors(missing_grant, dispatcher))
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
                {"id": 0, "name": "check_plain", "args": "file, table", "condition": None,
                 "suffix": "", "scope": ""},
                {"id": 1, "name": "check_global", "args": "file, table", "condition": None,
                 "suffix": "", "scope": "can Global{Read,Write}"},
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

    def test_chunked_dispatcher_preserves_order_and_checks_range_coverage(self):
        calls = [
            (pid, {"name": f"check_{pid}", "args": "file, table", "suffix": "", "scope": ""})
            for pid in range(55)
        ]
        source = audit.passes_source([], calls, 3)
        self.assertIn(
            "-> void can[Unsafe{PointerArithmetic,PointerCast,RawExtern}]:",
            source,
        )
        self.assertIn(
            "can Memory.Allocate, Abort.Panic, Global{Read,Write}, Unsafe{PointerArithmetic,PointerCast,RawExtern}:",
            source,
        )
        records, errors = audit.parse_parallel_dispatch(source)
        self.assertEqual(errors, [])
        self.assertEqual([record["id"] for record in records], list(range(55)))
        self.assertEqual(
            audit.parallel_dispatch_chunk_errors(source, list(range(55))),
            [],
        )
        broken = source.replace(
            "if pass_id >= 24 and pass_id <= 47:",
            "if pass_id >= 24 and pass_id <= 46:",
            1,
        )
        self.assertTrue(audit.parallel_dispatch_chunk_errors(broken, list(range(55))))

    def test_generated_chunk_dispatcher_write_round_trip_is_stable(self):
        definitions, globals_, mutable_refs, aliases, table_fields, struct_fields, variants = audit.parse_functions()
        info = audit.analyze(
            definitions, globals_, mutable_refs, aliases, table_fields, struct_fields, variants
        )
        flat, flags, calls, runs = audit.emit(info)
        self.assertFalse(calls, "fixture expects a fully generated semantic pipeline")
        generated_counts = [
            int(match.group(5))
            for line in flat
            for match in [audit.PAR_RUN_RE.search(line)]
            if match
        ]
        max_batch = max(generated_counts)
        path = Path(audit.PASSES)
        original = path.read_text(encoding="utf-8")
        records, errors = audit.parse_parallel_dispatch(original)
        self.assertEqual(errors, [])

        regenerated = audit.passes_source(flags, [(record["id"], record) for record in records], max_batch)
        safe_ids = {record["id"] for record in records if audit.append_only(info, record["name"])[0]}
        regenerated = audit.refresh_parallel_safety_gate(regenerated, safe_ids)
        regenerated = audit.refresh_max_batch(regenerated, max_batch)
        regenerated = audit.refresh_pass_flags(regenerated, flags)
        regenerated = audit.refresh_dispatch_table_region(regenerated)
        records, errors = audit.parse_parallel_dispatch(regenerated)
        self.assertEqual(errors, [])
        safe_ids = {record["id"] for record in records if audit.append_only(info, record["name"])[0]}
        regenerated = audit.refresh_parallel_safety_gate(regenerated, safe_ids)
        self.assertEqual(regenerated, original)

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

