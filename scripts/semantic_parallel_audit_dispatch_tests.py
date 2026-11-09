from pathlib import Path
import re
import unittest

from semantic_parallel_audit_test_support import (TABLE_FIELD_TYPES, analyze, audit, definition, diagnostic_audit)


class SemanticParallelDispatchTests(unittest.TestCase):
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
