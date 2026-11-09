#!/usr/bin/env python3
"""Audit and generate the concurrent runs of append-only semantic passes (round 8).

A semantic pass may run on a worker thread over a frozen SymbolTable only if it is
APPEND-ONLY: through every function it can reach, the only SymbolTable field it writes is
`diagnostics`, it never reads earlier diagnostics, and it writes no mutable global. This script
audits that from the source, conservatively:

  * the call graph is by name and a name with several definitions (overloads, methods of the
    same name in different modules) reaches ALL of them;
  * a write is any `<table>.<field>... <-`, any mutating container call on a table field,
    any `in <table>.<field>:` region block and any `&<table>.<field>` borrow (read-only borrows
    included), where <table> is any parameter or local declared with a SymbolTable type;
  * a diagnostics read is any use of `<table>.diagnostics` other than `<- ....push(` on it;
  * a global write is any assignment to, borrow of, or `in <global>:` region block over a
    `global mutable` name;
  * an AST write is any AST node construction (a variant of Expr/Stmt/Decl/Pattern/Node used
    as a value): it grows the shared AST store.
  * local aliases of table fields are tracked; writes through them and calls that pass a table
    field or alias as an explicit argument or method receiver to a `mutable` / `lmut` formal are
    conservatively rejected. Whole-table aliases and borrows are tracked; declared `extern`
    calls and calls outside the source call graph that receive table-backed values are rejected
    because their effects cannot be inspected.
    Local aliases of diagnostics are treated as reads because they may inspect earlier-pass
    results.

Passes run in `check_full_into_pipeline` (the pipeline source under `semantic_api/`) as `table <- pass(ARGS) [if COND]`. A
maximal run of consecutive append-only passes whose ARGS/COND use only `file`, `loop_view`,
`table` and the function's scalar flags becomes one `par_pass_run` call; the passes go into
semantic_parallel_passes.elisa by id, in pipeline order (the splice order).

  semantic_parallel_gen.py --check      verify every pass in semantic_parallel_passes.elisa
                                        (exit 1 naming each one that is not append-only)
  semantic_parallel_gen.py --write      rewrite the pipeline source + the passes file
                                        (input: sequential or already generated pipeline)
  semantic_parallel_gen.py --report     list every pipeline pass and its classification
"""
import collections
from functools import lru_cache
import os
import re
import sys

# Shared services preserve one audit configuration across the responsibility modules.
import semantic_parallel_source_scan
import semantic_parallel_syntax_walk
import semantic_parallel_alias_analysis
import semantic_parallel_type_properties
import semantic_parallel_type_resolution
import semantic_parallel_call_analysis
import semantic_parallel_effect_analysis
import semantic_parallel_pipeline_generation
import semantic_parallel_generation_checks
import semantic_parallel_runtime_checks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
PASSES = os.path.join(SRC, "semantic", "semantic_parallel_passes.elisa")
PIPELINE = "check_full_into_pipeline"
API_CANDIDATES = (
    os.path.join(SRC, "semantic", "semantic_api.elisa"),
    os.path.join(SRC, "semantic", "semantic_api", "full_pipeline.elisa"),
)
API = next(
    (path for path in API_CANDIDATES
     if os.path.isfile(path) and re.search(
         r"^\s*def " + PIPELINE + r"(?:\[[^\]]*\])?\(",
         open(path, encoding="utf-8").read(), re.M)),
    API_CANDIDATES[0],
)
PIPELINE_CONTEXT = {
    "file", "table", "shared_pool", "snapshot", "incremental_skip_count",
    "effect_source_bodies_skipped", "ungranted_panic_bodies_skipped",
    "global_permission_axis_scans_skipped", "lookup_session", "lookup_context",
    "enforce_mutable_global_grants",
}
MIN_RUN = 2
MUTATORS = (
    r"push|push_back|extend|pop|clear|insert|remove|remove_at|put|put_checked|put_or_panic|add|set|swap|sort"
    r"|append|append_many|truncate|reserve|resize|as_cstr|get_or_insert|get_or_insert_with|discard"
    r"|reverse|fill|push_front|pop_front|retain|drain"
)
# Source audit of table-backed receiver calls in src/semantic found these built-in
# read-only conversions/lookups. Any other unresolved receiver method is treated as
# an effectful call below; source-defined methods still use their formal modes.
READ_ONLY_TABLE_METHODS = {"get", "as_sview"}
READ_ONLY_TABLE_CALLS: set[str] = set()
BUILTIN_NUMERIC_CAST_METHODS = {
    "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64",
    "isize", "usize", "int", "uintptr", "char", "f32", "f64",
}
BORROWED_NAME_PREFIX = r"(?:(?:\(\s*)|(?:&\s*))*"
NON_CALL_KEYWORDS = {
    "if", "elif", "else", "while", "for", "match", "can", "catch", "and", "or", "not",
    "return", "mutable", "where", "assert", "ensure", "implies",
}
# Source-language intrinsics without ordinary source definitions. Keep this list
# narrow: an unresolved free call is an unknown effect unless explicitly known pure.
PURE_FREE_CALLS = {"sview", "getenv"}
# Ghost definitions are verification-only, but their bodies are still useful to the
# audit when a proof contract calls them. Analyzing their real call graph avoids
# misclassifying a known pure ghost helper as an unknown runtime effect.
DEF_RE = re.compile(r"^(\s*)(?:ghost\s+)?def (\w+)(?:\[[^\]]*\])?\((.*?)\)\s*(?:->|:)")
EXTERN_FUNC_RE = re.compile(r"^\s*extern\s+(\w+)\s*\(")
TABLE_DECL_RE = re.compile(r"\b(\w+)\s*:\s*(?:lmut\s+|mutable\s+|heap\s+)*SymbolTable\b")
GLOBAL_RE = re.compile(r"^\s*global\s+mutable\s+(\w+)(?:\s*:\s*([^#=\n]*))?")
TYPE_ALIAS_RE = re.compile(r"^\s*type\s+(\w+)(?:\[[^\]\n]*\])?\s*=\s*([^#\n]+)")
STRUCT_RE = re.compile(r"^(\s*)struct\s+(\w+)(?:\[[^\]\n]*\])?\s*:\s*$")
STRUCT_FIELD_RE = re.compile(r"^\s+(\w+)\s*:\s*([^#=\n]+)")
CONST_ENUM_RE = re.compile(r"^\s*const\s+enum\s+(\w+)\b")
ENUM_RE = re.compile(r"^(\s*)(?:const\s+)?enum\s+(\w+)\b.*:\s*$")
ENUM_VARIANT_RE = re.compile(r"^\s+([A-Z]\w*)\b")
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)[ \t]*(?:\[[^\]\n]*\])?[ \t]*\(")
PAR_RUN_RE = re.compile(
    r"^([ \t]*)(table <- )?par_pass_run\(file, flags, table, shared_pool, "
    r"(loop_view|&[A-Za-z_]\w*\[\d+\]), (\d+), (\d+)\)([ \t]+can[ \t]+[^\n]+)?[ \t]*$"
)
PAR_RUN_ANY_RE = re.compile(r"\bpar_pass_run\s*\(")
MUTABLE_POINTER_CAST_RE = re.compile(
    r"(?:\(\s*&?\s*)*\b(?P<root>\w+)\b"
    r"(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*\s*\)*"
    r"\s*\.\s*cast\s*\[(?P<target>[^\]\n]+)\]"
)
PAR_PASS_ARM_RE = re.compile(r"^([ \t]*)(if|elif) pass_id == (\d+):[ \t]*$")
PAR_PASS_ARM_ANY_RE = re.compile(r"\bpass_id\s*==")
PAR_PASS_DISPATCH_CHUNK_SIZE = 24


def elisa_files(*args, **kwargs):
    return semantic_parallel_source_scan.elisa_files(globals(), *args, **kwargs)


def type_expression_is_mutable_ref(*args, **kwargs):
    return semantic_parallel_source_scan.type_expression_is_mutable_ref(globals(), *args, **kwargs)


def parse_functions(*args, **kwargs):
    return semantic_parallel_source_scan.parse_functions(globals(), *args, **kwargs)


def strip_comments(*args, **kwargs):
    return semantic_parallel_source_scan.strip_comments(globals(), *args, **kwargs)


def mask_string_literals(*args, **kwargs):
    return semantic_parallel_source_scan.mask_string_literals(globals(), *args, **kwargs)


_FIELD_DOT_SPACING_RE = re.compile(r"(?<=[\w\]\)])(?:[ \t]+\.[ \t]*|\.[ \t]+)(?=\w)")


def audit_normalize_field_dots(*args, **kwargs):
    return semantic_parallel_source_scan.audit_normalize_field_dots(globals(), *args, **kwargs)


def par_run_calls(*args, **kwargs):
    return semantic_parallel_source_scan.par_run_calls(globals(), *args, **kwargs)


def normalized_par_run_line(*args, **kwargs):
    return semantic_parallel_source_scan.normalized_par_run_line(globals(), *args, **kwargs)


def split_parallel_range(*args, **kwargs):
    return semantic_parallel_source_scan.split_parallel_range(globals(), *args, **kwargs)


def parse_parallel_dispatch(*args, **kwargs):
    return semantic_parallel_syntax_walk.parse_parallel_dispatch(globals(), *args, **kwargs)


AST_VARIANT_RE = re.compile(r"(?<![\w.:])(?:Ast::)?(Expr|Stmt|Decl|Pattern|Node)\.([A-Z]\w*)\b")


def match_arm_body(*args, **kwargs):
    return semantic_parallel_syntax_walk.match_arm_body(globals(), *args, **kwargs)


def ast_constructions(*args, **kwargs):
    return semantic_parallel_syntax_walk.ast_constructions(globals(), *args, **kwargs)


def split_top_level_arguments(*args, **kwargs):
    return semantic_parallel_syntax_walk.split_top_level_arguments(globals(), *args, **kwargs)


def receiver_before_call(*args, **kwargs):
    return semantic_parallel_syntax_walk.receiver_before_call(globals(), *args, **kwargs)


def matching_delimiter(*args, **kwargs):
    return semantic_parallel_syntax_walk.matching_delimiter(globals(), *args, **kwargs)


def global_path_is_invoked(*args, **kwargs):
    return semantic_parallel_syntax_walk.global_path_is_invoked(globals(), *args, **kwargs)


def global_path_write_tail(*args, **kwargs):
    return semantic_parallel_syntax_walk.global_path_write_tail(globals(), *args, **kwargs)


def call_sites(*args, **kwargs):
    return semantic_parallel_syntax_walk.call_sites(globals(), *args, **kwargs)


def local_table_aliases(*args, **kwargs):
    return semantic_parallel_alias_analysis.local_table_aliases(globals(), *args, **kwargs)


def local_global_aliases(*args, **kwargs):
    return semantic_parallel_alias_analysis.local_global_aliases(globals(), *args, **kwargs)


COPY_VALUE_TYPE_NAMES = {
    "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64",
    "isize", "usize", "int", "f32", "f64", "bool", "char", "sview",
}


def copy_alias_view_base_type(*args, **kwargs):
    return semantic_parallel_type_properties.copy_alias_view_base_type(globals(), *args, **kwargs)


def type_is_copy_value(*args, **kwargs):
    return semantic_parallel_type_properties.type_is_copy_value(globals(), *args, **kwargs)


def type_may_contain_reference(*args, **kwargs):
    return semantic_parallel_type_properties.type_may_contain_reference(globals(), *args, **kwargs)


def type_may_contain_mutable_alias(*args, **kwargs):
    return semantic_parallel_type_properties.type_may_contain_mutable_alias(globals(), *args, **kwargs)


def type_is_top_level_reference(*args, **kwargs):
    return semantic_parallel_type_properties.type_is_top_level_reference(globals(), *args, **kwargs)


def is_detached_copy_value(*args, **kwargs):
    return semantic_parallel_type_properties.is_detached_copy_value(globals(), *args, **kwargs)


def mutable_cast_source_names(*args, **kwargs):
    return semantic_parallel_alias_analysis.mutable_cast_source_names(globals(), *args, **kwargs)


def local_table_field_aliases(*args, **kwargs):
    return semantic_parallel_alias_analysis.local_table_field_aliases(globals(), *args, **kwargs)


def immutable_table_field_borrow_starts(*args, **kwargs):
    return semantic_parallel_alias_analysis.immutable_table_field_borrow_starts(globals(), *args, **kwargs)


def argument_is_table_field_or_alias(*args, **kwargs):
    return semantic_parallel_alias_analysis.argument_is_table_field_or_alias(globals(), *args, **kwargs)


def table_field_expression_type(*args, **kwargs):
    return semantic_parallel_alias_analysis.table_field_expression_type(globals(), *args, **kwargs)


@lru_cache(maxsize=128)
def local_declaration_types(*args, **kwargs):
    return semantic_parallel_alias_analysis.local_declaration_types(globals(), *args, **kwargs)


def local_path_expression_type(*args, **kwargs):
    return semantic_parallel_alias_analysis.local_path_expression_type(globals(), *args, **kwargs)


def returned_shared_paths_are_copies(*args, **kwargs):
    return semantic_parallel_alias_analysis.returned_shared_paths_are_copies(globals(), *args, **kwargs)


def is_builtin_darray_type(*args, **kwargs):
    return semantic_parallel_type_resolution.is_builtin_darray_type(globals(), *args, **kwargs)


def is_builtin_scalar_type(*args, **kwargs):
    return semantic_parallel_type_resolution.is_builtin_scalar_type(globals(), *args, **kwargs)


def function_return_type(*args, **kwargs):
    return semantic_parallel_type_resolution.function_return_type(globals(), *args, **kwargs)


def type_equivalents(*args, **kwargs):
    return semantic_parallel_type_resolution.type_equivalents(globals(), *args, **kwargs)


def receiver_dispatch_type_key(*args, **kwargs):
    return semantic_parallel_type_resolution.receiver_dispatch_type_key(globals(), *args, **kwargs)


def receiver_dispatch_type_equivalents(*args, **kwargs):
    return semantic_parallel_type_resolution.receiver_dispatch_type_equivalents(globals(), *args, **kwargs)


def receiver_method_has_source_dispatch(*args, **kwargs):
    return semantic_parallel_type_resolution.receiver_method_has_source_dispatch(globals(), *args, **kwargs)


def receiver_is_static_owner(*args, **kwargs):
    return semantic_parallel_type_resolution.receiver_is_static_owner(globals(), *args, **kwargs)


def matching_cast_candidate_indexes(*args, **kwargs):
    return semantic_parallel_type_resolution.matching_cast_candidate_indexes(globals(), *args, **kwargs)


def receiver_expression_type(*args, **kwargs):
    return semantic_parallel_type_resolution.receiver_expression_type(globals(), *args, **kwargs)


def receiver_method_is_known_intrinsic(*args, **kwargs):
    return semantic_parallel_type_resolution.receiver_method_is_known_intrinsic(globals(), *args, **kwargs)


def specialized_cast_definitions(*args, **kwargs):
    return semantic_parallel_type_resolution.specialized_cast_definitions(globals(), *args, **kwargs)


def argument_is_whole_table(*args, **kwargs):
    return semantic_parallel_call_analysis.argument_is_whole_table(globals(), *args, **kwargs)


def has_top_level_colon(*args, **kwargs):
    return semantic_parallel_call_analysis.has_top_level_colon(globals(), *args, **kwargs)


def return_value_before_guard(*args, **kwargs):
    return semantic_parallel_call_analysis.return_value_before_guard(globals(), *args, **kwargs)


def _top_level_conditional_keyword(*args, **kwargs):
    return semantic_parallel_call_analysis._top_level_conditional_keyword(globals(), *args, **kwargs)


def returned_value_arms(*args, **kwargs):
    return semantic_parallel_call_analysis.returned_value_arms(globals(), *args, **kwargs)


def returned_expressions(*args, **kwargs):
    return semantic_parallel_call_analysis.returned_expressions(globals(), *args, **kwargs)


def argument_is_table_backed(*args, **kwargs):
    return semantic_parallel_call_analysis.argument_is_table_backed(globals(), *args, **kwargs)


def is_diagnostics_receiver(*args, **kwargs):
    return semantic_parallel_call_analysis.is_diagnostics_receiver(globals(), *args, **kwargs)


def mutable_actual_indexes(*args, **kwargs):
    return semantic_parallel_call_analysis.mutable_actual_indexes(globals(), *args, **kwargs)


def _matched_source_names(*args, **kwargs):
    return semantic_parallel_call_analysis._matched_source_names(globals(), *args, **kwargs)


def _global_callable_names(*args, **kwargs):
    return semantic_parallel_call_analysis._global_callable_names(globals(), *args, **kwargs)


def argument_global_names(*args, **kwargs):
    return semantic_parallel_call_analysis.argument_global_names(globals(), *args, **kwargs)


def call_may_mutate_table_field(*args, **kwargs):
    return semantic_parallel_call_analysis.call_may_mutate_table_field(globals(), *args, **kwargs)


def analyze(*args, **kwargs):
    return semantic_parallel_effect_analysis.analyze(globals(), *args, **kwargs)


def closure_facts(*args, **kwargs):
    return semantic_parallel_pipeline_generation.closure_facts(globals(), *args, **kwargs)


def append_only(*args, **kwargs):
    return semantic_parallel_pipeline_generation.append_only(globals(), *args, **kwargs)


def pipeline_statements(*args, **kwargs):
    return semantic_parallel_pipeline_generation.pipeline_statements(globals(), *args, **kwargs)


TABLE_CALL_PREFIX_RE = re.compile(r"^([ \t]*)table <- (\w+)\(")
TIMER_RE = re.compile(r'^\s*PhaseTimer::minor\("[^"]*"\)$')


def parse_table_call_statement(*args, **kwargs):
    return semantic_parallel_pipeline_generation.parse_table_call_statement(globals(), *args, **kwargs)


def eligible_args(*args, **kwargs):
    return semantic_parallel_pipeline_generation.eligible_args(globals(), *args, **kwargs)


def plan_runs(*args, **kwargs):
    return semantic_parallel_pipeline_generation.plan_runs(globals(), *args, **kwargs)


def has_mixed_generated_and_sequential_runs(*args, **kwargs):
    return semantic_parallel_pipeline_generation.has_mixed_generated_and_sequential_runs(globals(), *args, **kwargs)


def emit(*args, **kwargs):
    return semantic_parallel_pipeline_generation.emit(globals(), *args, **kwargs)


PARALLEL_GATE_BEGIN = "        # BEGIN GENERATED APPEND-ONLY GATE"
PARALLEL_GATE_END = "        # END GENERATED APPEND-ONLY GATE"


def parallel_safety_gate_source(*args, **kwargs):
    return semantic_parallel_generation_checks.parallel_safety_gate_source(globals(), *args, **kwargs)


def refresh_parallel_safety_gate(*args, **kwargs):
    return semantic_parallel_generation_checks.refresh_parallel_safety_gate(globals(), *args, **kwargs)


def parallel_safety_gate_errors(*args, **kwargs):
    return semantic_parallel_generation_checks.parallel_safety_gate_errors(globals(), *args, **kwargs)


def parallel_runtime_serial_guard_errors(*args, **kwargs):
    return semantic_parallel_generation_checks.parallel_runtime_serial_guard_errors(globals(), *args, **kwargs)


def parallel_runtime_lmut_errors(*args, **kwargs):
    return semantic_parallel_generation_checks.parallel_runtime_lmut_errors(globals(), *args, **kwargs)


def passes_source(*args, **kwargs):
    return semantic_parallel_generation_checks.passes_source(globals(), *args, **kwargs)


def parallel_dispatch_chunk_errors(*args, **kwargs):
    return semantic_parallel_generation_checks.parallel_dispatch_chunk_errors(globals(), *args, **kwargs)


def refresh_max_batch(*args, **kwargs):
    return semantic_parallel_generation_checks.refresh_max_batch(globals(), *args, **kwargs)


def refresh_pass_flags(*args, **kwargs):
    return semantic_parallel_generation_checks.refresh_pass_flags(globals(), *args, **kwargs)


def refresh_dispatch_table_region(*args, **kwargs):
    return semantic_parallel_generation_checks.refresh_dispatch_table_region(globals(), *args, **kwargs)


def generated_parallel_errors(*args, **kwargs):
    return semantic_parallel_runtime_checks.generated_parallel_errors(globals(), *args, **kwargs)


def parallel_runtime_view_errors(*args, **kwargs):
    return semantic_parallel_runtime_checks.parallel_runtime_view_errors(globals(), *args, **kwargs)


def pipeline_scratch_errors(*args, **kwargs):
    return semantic_parallel_runtime_checks.pipeline_scratch_errors(globals(), *args, **kwargs)


def listed_passes(*args, **kwargs):
    return semantic_parallel_runtime_checks.listed_passes(globals(), *args, **kwargs)


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--check"
    (
        defs, globals_, mutable_ref_globals, type_aliases, table_field_types,
        struct_field_types, enum_variants,
    ) = parse_functions()
    info = analyze(
        defs, globals_, mutable_ref_globals, type_aliases, table_field_types,
        struct_field_types, enum_variants,
    )
    if mode == "--check":
        bad = []
        bad.extend(generated_parallel_errors(info))
        if bad:
            print("semantic_parallel_gen: passes run concurrently that are NOT append-only:")
            for b in bad:
                print("  " + b)
            return 1
        from semantic_parallel_diagnostic_audit import main as audit_diagnostic_ownership
        try:
            audit_diagnostic_ownership()
        except AssertionError as error:
            print("semantic_parallel_gen: " + str(error))
            return 1
        dispatch, _errors = parse_parallel_dispatch(open(PASSES, encoding="utf-8").read())
        safe_count = sum(append_only(info, record["name"])[0] for record in dispatch)
        print("semantic_parallel_gen: %d passes audited; %d parallel-eligible, %d serialized" % (
            len(dispatch), safe_count, len(dispatch) - safe_count
        ))
        return 0
    if mode == "--report":
        _lines, _flags, stmts, runs = plan_runs(info)
        in_run = {s["line"] for r in runs for s in r}
        for s in stmts:
            ok, writes, reads = append_only(info, s["name"])
            tag = "RUN " if s["line"] in in_run else ("ok  " if ok else "seq ")
            print(tag, s["name"], "" if ok else sorted(writes)[:6], "reads-diag" if reads else "")
        print("runs", len(runs), "passes in runs", sum(len(r) for r in runs), "of", len(stmts))
        return 0
    if mode == "--write":
        try:
            flat, flags, calls, runs = emit(info)
        except ValueError as error:
            print("semantic_parallel_gen: refusing --write: " + str(error))
            return 1
        open(API, "w", encoding="utf-8").write("\n".join(flat))
        generated_counts = [int(m.group(5)) for line in flat for m in [PAR_RUN_RE.search(line)] if m]
        if calls or not generated_counts:
            max_batch = max((len(run) for run in runs), default=1)
            pass_source = passes_source(flags, calls, max_batch)
            open(PASSES, "w", encoding="utf-8").write(pass_source)
        else:
            max_batch = max(generated_counts)
            current = open(PASSES, encoding="utf-8").read()
            dispatch, dispatch_errors = parse_parallel_dispatch(current)
            if dispatch_errors:
                print("semantic_parallel_gen: refusing --write: " + "; ".join(dispatch_errors))
                return 1
            dispatch_calls = [(record["id"], record) for record in dispatch]
            current = passes_source(flags, dispatch_calls, max_batch)
            safe_ids = {
                record["id"] for record in dispatch
                if append_only(info, record["name"])[0]
            }
            current = refresh_parallel_safety_gate(current, safe_ids)
            current = refresh_max_batch(current, max_batch)
            current = refresh_pass_flags(current, flags)
            current = refresh_dispatch_table_region(current)
            dispatch, dispatch_errors = parse_parallel_dispatch(current)
            if dispatch_errors:
                print("semantic_parallel_gen: refusing --write: " + "; ".join(dispatch_errors))
                return 1
            safe_ids = {
                record["id"] for record in dispatch
                if append_only(info, record["name"])[0]
            }
            current = refresh_parallel_safety_gate(current, safe_ids)
            open(PASSES, "w", encoding="utf-8").write(current)
        print("semantic_parallel_gen: %d runs, %d passes; flags %s" % (len(runs), len(calls), flags))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
