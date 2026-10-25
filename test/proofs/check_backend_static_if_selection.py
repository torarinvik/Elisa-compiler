"""Admit the source-linked static-if branch-selection policy proof."""
from __future__ import annotations

import hashlib
import json
import os
import argparse
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check source bindings without requiring the proof/compiler artifacts")
ARGS = argument_parser.parse_args()


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
BRANCH_TAGS = ROOT / "src/parser/static_if_branch.elisa"
PARSER_FACADE = ROOT / "src/parser/parser.elisa"
PARSER_CORE = ROOT / "src/parser/parser_core.elisa"
PARSER_CORE_MEMBER_TABLES = ROOT / "src/parser/parser_core_member_tables.elisa"
PARSER_TOKENS = ROOT / "src/parser/parser_tokens.elisa"
PARSER_DECL = ROOT / "src/parser/parser_decl.elisa"
PARSER_DECL_IMPL = ROOT / "src/parser/parser_decl_impl.elisa"
PARSER_DECL_MODULE = ROOT / "src/parser/parser_decl_module.elisa"
PARSER_STMT = ROOT / "src/parser/parser_stmt.elisa"
PARSER_TYPES_ENTRY = ROOT / "src/parser/parser_types_entry.elisa"
BACKEND_FACADE = ROOT / "src/backend/codegen_struct_reg.elisa"
CODEGEN_MODULE = ROOT / "src/backend/codegen_module.elisa"
CODEGEN_STMT = ROOT / "src/backend/codegen_stmt_blocks_exprs.elisa"
CODEGEN_TABLE = ROOT / "src/backend/codegen_struct_table.elisa"
CODEGEN_DECL_HOISTING = ROOT / "src/backend/codegen_decl_hoisting.elisa"
DRIVER_UNSAFE = ROOT / "src/driver/elisac_emit_unsafe_report.elisa"
DRIVER_UNSAFE_SEGMENTS = ROOT / "src/driver/elisac_emit_unsafe_report_segments.elisa"
POLICY = ROOT / "src/backend/codegen_static_if_policy.elisa"
SELECTOR = ROOT / "src/backend/codegen_static_if.elisa"
MEXT = ROOT / "src/semantic/check_module_extension_target.elisa"
FILE_VIEW = ROOT / "src/semantic/semantic_loop_view.elisa"
STATIC_IF_CONDITION = ROOT / "src/semantic/check_static_if_condition.elisa"
FULL_PIPELINE = ROOT / "src/semantic/semantic_api/full_pipeline.elisa"
DRIVER_AST_DECL = ROOT / "src/driver/elisac_emit_ast_decl.elisa"
STATIC_RUNTIME = ROOT / "src/semantic/check_static_runtime_stmt.elisa"
STATIC_RUNTIME_FIXTURE = ROOT / "test/repro/static_block_runtime_call_line_reset_rejected.elisa"
STATIC_RUNTIME_NESTED_FIXTURE = ROOT / "test/repro/static_if_inside_bare_static_runtime.elisa"
STATIC_RUNTIME_INACTIVE_FIXTURE = ROOT / "test/repro/static_if_inactive_nested_bare_static.elisa"
STATIC_RUNTIME_SIBLING_FIXTURE = ROOT / "test/repro/static_runtime_sibling_static_name.elisa"
STATIC_RUNTIME_IMPORT_FIXTURE = ROOT / "test/repro/static_block_imported_runtime_call.elisa"
STATIC_RUNTIME_SMOKE = ROOT / "test/parity/static_if_runtime_call_smoke.sh"
STATIC_FN_FILTER_FIXTURE = ROOT / "test/repro/static_function_nested_offset_filter.elisa"
STATIC_FN_FILTER_SMOKE = ROOT / "test/parity/static_function_nested_offset_filter_smoke.sh"
STATIC_CALL_CONTEXT = ROOT / "src/semantic/check_static_call_context.elisa"
STATIC_CALL_CONTEXT_FIXTURE = ROOT / "test/repro/static_call_context_module_identity.elisa"
STATIC_CALL_CONTEXT_SMOKE = ROOT / "test/parity/static_call_context_module_identity_smoke.sh"
LEXICAL_MODULE_FIXTURE = ROOT / "test/repro/static_if_condition_lexical_module.elisa"
LEXICAL_MODULE_SMOKE = ROOT / "test/parity/static_if_condition_lexical_module_smoke.sh"
TRY_FALLIBLE = ROOT / "src/semantic/check_try_fallible.elisa"
BACKEND_ID_FIXTURE = ROOT / "test/repro/static_if_same_line_heads.elisa"
MANUAL_FILE_LITERAL = ROOT / "test/repro/cpu_optional_goal_allocation_probe.elisa"
POSITIVE = HERE / "backend_static_if_selection.elisa"
NEGATIVE = HERE / "backend_static_if_selection_rejected.elisa"

PROOF_PROCESS_TIMEOUT_SECONDS = 60
ELISA_INDENT_WIDTH = 4
POSITIVE_NAMES = {
    "every_branch_kind_has_its_exact_action",
    "a_chain_head_starts_fresh_even_after_a_selected_outer_arm",
    "an_unsatisfied_chain_continuation_evaluates_its_condition",
    "an_unsatisfied_fallback_is_selected_without_folding_a_condition",
    "a_satisfied_chain_skips_a_continuation",
    "a_satisfied_chain_skips_its_fallback",
    "condition_selection_matches_foldability_and_truth",
    "an_unfoldable_condition_is_not_selected",
    "a_zero_condition_is_not_selected",
}
NEGATIVE_NAMES = {
    "false_claim_chain_head_is_suppressed_by_a_prior_selection",
    "false_claim_unsatisfied_continuation_is_skipped",
    "false_claim_unsatisfied_fallback_is_skipped",
    "false_claim_satisfied_fallback_is_selected",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def source_code(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def compact(text: str) -> str:
    return "".join(source_code(text).split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def direct_children(lines: list[str], parent_index: int, parent_indent: int) -> list[str]:
    children: list[str] = []
    for line in lines[parent_index + 1:]:
        content = line.lstrip(" \t")
        if not content or content.startswith("#"):
            continue
        indent = len(line) - len(content)
        if indent <= parent_indent:
            break
        if indent == parent_indent + ELISA_INDENT_WIDTH:
            children.append(content)
    return children


def require_branch_kind_contract() -> None:
    branch_text = compact(BRANCH_TAGS.read_text())
    expected = (
        "moduleStaticIfBranch:public:constenumKindofu32:ChainHead"
        "ChainContinuationFallbackconstTOP_LEVEL_DEPTH:u32=0"
        "constNESTING_LEVEL_STEP:u32=1constCONDITION_FALSE_VALUE:i64=0"
    )
    if expected not in branch_text:
        raise SystemExit("shared static-if branch tags or named depth/false constants changed")
    parser_facade = compact(PARSER_FACADE.read_text())
    backend_facade = compact(BACKEND_FACADE.read_text())
    if 'include"./static_if_branch.elisa"' not in parser_facade:
        raise SystemExit("parser no longer includes the shared static-if branch tags")
    backend_order = [
        backend_facade.find('include"./codegen_static_if_policy.elisa"'),
        backend_facade.find('include"./codegen_static_if.elisa"'),
    ]
    if any(position < 0 for position in backend_order) or backend_order != sorted(backend_order):
        raise SystemExit("backend must include the policy before the selector; branch tags come through Parser")


def require_parser_emission() -> None:
    declaration = compact(function_section(PARSER_DECL.read_text(), "capture_static_if_condition"))
    expected = (
        "branch_kind:StaticIfBranch::Kind=StaticIfBranch::Kind.ChainHeadifis_chain_headelseStaticIfBranch::Kind.ChainContinuation"
        "parser.static_if_kinds<-parser.static_if_kinds.push(branch_kind)"
    )
    if expected not in declaration:
        raise SystemExit("parser must derive typed tags for static-if and static-elif row kinds")
    fallback = compact(function_section(PARSER_DECL.read_text(), "record_static_else"))
    if "StaticIfBranch::Kind.Fallback" not in fallback or "push(2)" in fallback:
        raise SystemExit("parser fallback rows must use the shared named branch kind")
    if "StaticIfBranch::TOP_LEVEL_DEPTH" not in compact(PARSER_CORE_MEMBER_TABLES.read_text()):
        raise SystemExit("parser static-if nesting must start at the named top-level depth")
    for path in (PARSER_DECL_IMPL, PARSER_STMT):
        text = compact(path.read_text())
        if "static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP" not in text:
            raise SystemExit(f"{path.name} must use the named static-if nesting increment")
        if "static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP" not in text:
            raise SystemExit(f"{path.name} must use the named static-if nesting decrement")


def require_static_if_row_alignment() -> None:
    columns = ("static_if_conds", "static_if_modules", "static_if_lines", "static_if_offsets", "static_if_kinds", "static_if_depths")
    append_values = {
        "capture_static_if_condition": ("condition_expr", "parser.current_module", "branch_line", "branch_offset", "branch_kind", "parser.static_if_depth"),
        "record_static_else": ("(Ast::Expr.Absent)", "parser.current_module", "branch_line", "branch_offset", "StaticIfBranch::Kind.Fallback", "parser.static_if_depth"),
    }
    for function_name, values in append_values.items():
        section = compact(function_section(PARSER_DECL.read_text(), function_name))
        fragments = [f"parser.{column}<-parser.{column}.push({value})" for column, value in zip(columns, values)]
        positions = [section.find(fragment) for fragment in fragments]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            raise SystemExit(f"{function_name} must append all six static-if row columns in lockstep")
        if any(section.count(fragment) != 1 for fragment in fragments):
        raise SystemExit(f"{function_name} must append each static-if row column exactly once")
    parser_core = compact(PARSER_CORE.read_text())
    constructor = compact(PARSER_CORE_MEMBER_TABLES.read_text())
    for column in columns:
        if constructor.count(f"{column}:[]") != 1:
            raise SystemExit(f"parser constructor must initialize the {column} row column exactly once")
    if "static_if_kinds:mutabledarray[StaticIfBranch::Kind]" not in parser_core:
        raise SystemExit("parser must keep static-if tags in the closed branch-kind enum")
    if "static_if_offsets:mutabledarray[u32]" not in parser_core:
        raise SystemExit("parser must preserve the static-head offset alongside every static-if row")
    if "static_if_modules:mutabledarray[sview@source]" not in parser_core:
        raise SystemExit("parser must preserve the lexical module for each static-if row")
    token_types = compact(PARSER_TOKENS.read_text())
    if "static_if_kinds:darray[StaticIfBranch::Kind]" not in token_types:
        raise SystemExit("Ast::File must keep static-if tags in the closed branch-kind enum")
    if "static_if_offsets:darray[u32]" not in token_types:
        raise SystemExit("Ast::File must carry the static-head offsets alongside every static-if row")
    if "static_if_modules:darray[sview@source]" not in token_types:
        raise SystemExit("Ast::File must preserve each static-if condition's lexical module")
    entry = compact(function_section(PARSER_TYPES_ENTRY.read_text(), "parse_file_seeded"))
    positions = [entry.find(f"{column}:parser.{column}") for column in columns]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("Ast::File construction must transfer all static-if row columns in lockstep")
    if any(entry.count(f"{column}:parser.{column}") != 1 for column in columns):
        raise SystemExit("Ast::File construction must transfer each static-if row column exactly once")
    file_view = compact(FILE_VIEW.read_text())
    if "static_if_offsets:file.static_if_offsets" not in file_view:
        raise SystemExit("semantic Ast::File rewrites must preserve static-if head offsets")
    if "static_if_modules:file.static_if_modules" not in file_view:
        raise SystemExit("semantic Ast::File rewrites must preserve static-if lexical modules")
    if "static_if_offsets:[]" not in compact(MANUAL_FILE_LITERAL.read_text()):
        raise SystemExit("manual Ast::File fixtures must initialize the static-if head offset column")
    if "static_if_modules:[]" not in compact(MANUAL_FILE_LITERAL.read_text()):
        raise SystemExit("manual Ast::File fixtures must initialize the static-if module column")

    branch_row = compact(function_section(MEXT.read_text(), "mext_branch_row"))
    extension_identity = compact(function_section(MEXT.read_text(), "mext_is_extension"))
    extension_parser = compact(function_section(PARSER_DECL_MODULE.read_text(), "module_declaration"))
    collector = compact(function_section(MEXT.read_text(), "mext_collect"))
    entrypoint = compact(function_section(MEXT.read_text(), "check_module_extension_target"))
    if not all(fragment in branch_row for fragment in (
            "static_if_offsets:darray[u32]&",
            "position:Ast::Pos",
            "static_if_lines[row]==position.line",
            "static_if_offsets[row]==position.offset",
            "return-1ifselected>=0")) or not all(fragment in collector for fragment in (
            "static_if_offsets:darray[u32]&",
            "mext_branch_row(static_if_lines,static_if_offsets,scoped_pos)",
            "mext_collect(module_body,annotations,static_if_lines,static_if_offsets")) or \
            "file.static_if_offsets" not in entrypoint or not all(fragment in extension_identity for fragment in (
            'annotation.owner=="__compiler_extension_module"',
            "annotation.name==name",
            "annotation.line==pos.line",
            "annotation.offset==pos.offset")) or \
            'offset:token.start' not in extension_parser or \
            'owner:"__compiler_extension_module",name:name,line:token.line,module:name,offset:token.start' not in extension_parser:
        raise SystemExit("module-extension tracking must match exact scoped-head and declaration positions, preserving ambiguity")


def require_static_runtime_block_identity() -> None:
    source = STATIC_RUNTIME.read_text()
    classifier = compact(function_section(source, "srs_static_if_branch_selection"))
    static_function = compact(function_section(source, "srs_static_function_at"))
    collector = compact(function_section(source, "srs_collect_functions"))
    function_kind = compact(function_section(source, "srs_function_kind"))
    candidate_visibility = compact(function_section(source, "srs_function_candidate_visibility"))
    static_walker = compact(function_section(source, "srs_walk_static"))
    walker = compact(function_section(source, "srs_walk"))
    checker = compact(function_section(source, "srs_check_declarations"))
    entrypoint = compact(function_section(source, "check_static_runtime_stmt"))
    if not all(fragment in classifier for fragment in (
            "position:Ast::Pos",
            "static_if_lines[row]==position.line",
            "file.static_if_offsets[row]==position.offset",
            "pma_static_if_row_selection(file,branch_row,current_module,table)")) or \
            not all(fragment in static_function for fragment in (
            'annotation.owner=="__static_fn"',
            "annotation.module==current_module",
            "annotation.line==position.line",
            "annotation.offset==position.offset")) or \
            not all(fragment in collector for fragment in (
            "srs_static_function_at(file,current_module,function_name,position)",
            "modules<-modules.push(current_module)",
            "srs_static_if_branch_selection(file,scoped_position,current_module,table)",
            "continueifbranch.foundandbranch.knownandnotbranch.active")) or \
            not all(fragment in function_kind for fragment in (
            "srs_module_contains(current_module,modules[row])",
            "lexical_staticandlexical_runtime",
            "candidate.lexical",
            "imported_uncertain")) or \
            not all(fragment in candidate_visibility for fragment in (
            "sgi_function_visible(file,file.enum_annotations,table,symbol,current_module)",
            "pma_static_if_function_branch_selection(file,name,symbol,table,0)",
            "return(true,visibility.known,visibility.visible,visibility.lexical,branch.known,branch.active)")) or \
            not all(fragment in static_walker for fragment in (
            "srs_static_if_branch_selection(file,position,current_module,table)",
            "notbranch.knownorbranch.active",
            "srs_walk(body,file,current_module,names,modules,lines,offsets,is_static,table)")) or \
            not all(fragment in walker for fragment in (
            "srs_static_if_branch_selection(file,position,current_module,table)",
            "notbranch.knownorbranch.active",
            "srs_walk_static(body,file,current_module,names,modules,lines,offsets,is_static,table)")) or \
            "continueifbranch.foundandbranch.knownandnotbranch.active" not in checker or \
            "srs_collect_functions(file.top_decls,\"\",file,table,function_names,function_modules,function_lines,function_offsets,function_is_static)" not in entrypoint:
        raise SystemExit("static-runtime analysis must use lexical function identity and prune proven-inactive nested static-if arms")
    fixture = STATIC_RUNTIME_FIXTURE.read_text()
    nested_fixture = STATIC_RUNTIME_NESTED_FIXTURE.read_text()
    inactive_fixture = STATIC_RUNTIME_INACTIVE_FIXTURE.read_text()
    sibling_fixture = STATIC_RUNTIME_SIBLING_FIXTURE.read_text()
    import_fixture = STATIC_RUNTIME_IMPORT_FIXTURE.read_text()
    smoke = STATIC_RUNTIME_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "#line 80 bare-static.elisa",
            "static:",
            "hook()",
            "#line 80 conditional-static-if.elisa",
            "static if true:")) or not all(fragment in nested_fixture for fragment in (
            "def hook() -> void:",
            "static:",
            "static if false:",
            "hook()")) or not all(fragment in smoke for fragment in (
            "static_if_inside_bare_static_runtime.elisa",
            "static_if_inactive_nested_bare_static.elisa",
            "static_runtime_sibling_static_name.elisa",
            "static_block_imported_runtime_call.elisa",
            "static_block_runtime_call_line_reset_rejected.elisa",
            "sibling-module runtime function",
            "proven-inactive static-if branch",
            "same #line value",
            "unrelated static-if head at the same #line value")):
        raise SystemExit("static-runtime regression must cover a bare block sharing a logical line with a later conditional head")
    if not all(fragment in inactive_fixture for fragment in (
            "static:",
            "static if false:",
            "static:",
            "hook()")) or not all(fragment in sibling_fixture for fragment in (
            "module Compile:",
            "static def emit()",
            "module Runtime:",
            "def emit()",
            "static:",
            "emit()")) or not all(fragment in import_fixture for fragment in (
            "module Provider:",
            "def via_wildcard()",
            "def via_selective()",
            "using Provider",
            "from Provider import via_selective",
            "via_wildcard()",
            "via_selective()")):
        raise SystemExit("static-runtime regression must cover inactive nested bare-static calls and sibling module name collisions")


def require_static_function_filter_identity() -> None:
    parser = compact(function_section(PARSER_DECL.read_text(), "parse_static"))
    backend_source = compact(CODEGEN_MODULE.read_text())
    declaration_match = compact(function_section(CODEGEN_MODULE.read_text(), "declaration_is_static_function"))
    recursive_filter = compact(function_section(CODEGEN_MODULE.read_text(), "declaration_without_static_functions"))
    if not all(fragment in parser for fragment in (
            'owner:"__static_fn"',
            "line:static_fn_pos.line",
            "offset:static_fn_pos.offset",
            "module:parser.current_module")):
        raise SystemExit("static-function parser rows must retain module and exact declaration position")
    if not all(fragment in declaration_match for fragment in (
            'annotation.owner=="__static_fn"',
            "annotation.name==function_name",
            "annotation.line==position.line",
            "annotation.offset==position.offset")):
        raise SystemExit("backend static-function filtering must match source declaration identity")
    if not all(fragment in recursive_filter for fragment in (
            "Decl.Module(module_name,module_body,module_pos)",
            "Decl.Scoped(scoped_body,scoped_pos)",
            "declaration_is_static_function(annotations,nested)",
            "declaration_without_static_functions(annotations,nested)")) or \
            "declaration_without_static_functions(static_fn_rows,kept_declaration)" not in backend_source:
        raise SystemExit("backend must recursively strip static functions from nested modules and impl scopes")
    fixture = STATIC_FN_FILTER_FIXTURE.read_text()
    smoke = STATIC_FN_FILTER_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "#line 70 static-helper.elisa",
            "module Outer:",
            "module Inner:",
            "static def helper()",
            "#line 70 runtime-helper.elisa",
            "module Kept:",
            "def helper()",
            "impl Value:",
            "static def compile_only_impl()")) or not all(fragment in smoke for fragment in (
            "static_function_nested_offset_filter.elisa",
            "grep -Ec '^[[:space:]]*define .*helper'",
            "compile_only_impl")):
        raise SystemExit("static-function regression must cover nested modules, impl scopes, and repeated #line identity")


def require_static_call_context_identity() -> None:
    source = STATIC_CALL_CONTEXT.read_text()
    declaration_match = compact(function_section(source, "is_static_function_declaration"))
    visible_match = compact(function_section(source, "is_visible_static_function"))
    branch_selection = compact(function_section(source, "static_call_function_branch_selection"))
    nearest_runtime = compact(function_section(source, "static_call_nearer_runtime_function_shadows"))
    inactive_scope = compact(function_section(source, "static_call_scope_is_inactive"))
    expression_walker = compact(function_section(source, "static_call_check_expression"))
    statement_walker = compact(function_section(source, "static_call_check_statements"))
    walker = compact(function_section(source, "check_static_call_context_walk"))
    entrypoint = compact(function_section(source, "check_static_call_context"))
    module_ancestor = compact(function_section(TRY_FALLIBLE.read_text(), "try_noncall_module_is_ancestor"))
    if not all(fragment in declaration_match for fragment in (
            'annotation.owner!="__static_fn"',
            "annotation.name==function_name",
            "annotation.line==function_position.line",
            "annotation.offset==function_position.offset",
            "annotation.module==current_module")):
        raise SystemExit("static-call body suppression must match the exact static declaration identity")
    if not all(fragment in visible_match for fragment in (
            'annotation.owner!="__static_fn"',
            "annotation.name!=function_name",
            "try_noncall_module_is_ancestor(annotation.module,current_module)",
            "static_call_nearer_runtime_function_shadows(file,annotation.module,current_module,function_name,table)",
            "static_call_function_branch_selection(annotation,file,table)",
            "returntrueifnotbranch.knownorbranch.active")):
        raise SystemExit("bare static calls must respect lexical visibility and exclude only statics proven inactive")
    if not all(fragment in branch_selection for fragment in (
            "symbol_chain_head(table,annotation.name)",
            "symbol.module_owner==annotation.module",
            "symbol.line==annotation.line",
            "symbol.offset==annotation.offset",
            "pma_static_if_function_branch_selection(file,annotation.name,symbol,table,0)")):
        raise SystemExit("static-call branch activity must bind the exact function symbol before filtering candidates")
    if not all(fragment in nearest_runtime for fragment in (
            "symbol.module_owner!=static_moduleandnottry_noncall_module_is_ancestor(static_module,symbol.module_owner)",
            "try_noncall_module_is_ancestor(static_module,symbol.module_owner)",
            "try_noncall_module_is_ancestor(symbol.module_owner,current_module)",
            'annotation.owner=="__static_fn"',
            "pma_static_if_function_branch_selection(file,function_name,symbol,table,0)",
            "returntrueifnotbranch.knownorbranch.active")):
        raise SystemExit("a nearer runtime declaration not proven inactive must shadow an ancestor static function")
    if not all(fragment in inactive_scope for fragment in (
            "pma_static_if_row_for_position(file,scope_position)",
            "pma_static_if_row_selection(file,branch_row,current_module,table)",
            "branch.knownandnotbranch.selected")):
        raise SystemExit("static-call walking must skip only scopes proven to be inactive static-if arms")
    if not all(fragment in expression_walker for fragment in (
            "defstatic_call_check_expression(file:Ast::File&",
            "Expr.Call(callee,arguments,argument_names,line)",
            "static_call_check_expression(file,callee",
            "static_call_check_expression(file,argument",
            "static_call_check_expression(file,left",
            "static_call_check_expression(file,right",
            "operator!=TokenKind.Isandoperator!=TokenKind.As",
            "Expr.StaticEffectCall(effect_type,operation,candidates,arguments,argument_names,pos)",
            "forcaptureincandidate.captures",
            "Expr.Field(object,field,pos)",
            "Expr.Scope(base,name,pos)",
            "Expr.Index(object,index,pos)",
            "Expr.Slice(object,low,high,pos)",
            "Expr.IndexN(object,arguments,pos)",
            "Expr.Move(operand,pos)",
            "Expr.RegionNew(operand,region,pos)",
            "Expr.Paren(inner,line)",
            "Expr.Array(elements,pos)|Expr.Tuple(elements,pos)|Expr.SetLit(elements,pos)",
            "Expr.DictLit(entries,pos)",
            "Expr.Construct(type_expression,fields,pos)",
            "Expr.RecordUpdate(base,fields,pos)",
            "Expr.If(condition,then_expr,else_expr,pos)",
            "Expr.Match(scrutinee,arms,pos)|Expr.Catch(scrutinee,arms,pos)",
            "Expr.Comprehension(variable,iterable,condition,body,pos,_)",
            "Expr.Refinement(base,predicate,pos)",
            "Expr.GetElse(guarded,recovery,pos)",
            "Expr.Lambda(parameters,body,pos)",
            "Expr.Block(statements,value,captures,pos)")) or not all(fragment in statement_walker for fragment in (
            "defstatic_call_check_statements(file:Ast::File&",
            "static_call_check_expression(file,expression",
            "Stmt.If(condition,then_body,else_body,line)",
            "Stmt.While(condition,while_body,line)",
            "Stmt.Assign(target,operator,value,line)",
            "static_call_check_expression(file,target",
            "Stmt.For(bind,variables,iterable,for_body,line)",
            "static_call_check_expression(file,iterable",
            "Stmt.Match(scrutinee,arms,line)",
            "Stmt.Contract(kind,expression,line)",
            'kind=="requires"orkind=="require"orkind=="assert"orkind=="ensure"orkind=="ensures"',
            "Stmt.Block(kind,clause,binding,body,line)",
            'kind!="static"',
            "static_call_check_statements(file,then_body",
            "static_call_check_statements(file,else_body")):
        raise SystemExit("static-call checking must recurse through runtime expression and statement children")
    if any(fragment in expression_walker for fragment in (
            "static_call_check_expression(file,type_expression",
            "static_call_check_expression(file,effect_type")) or "static_call_check_expression(file,type_expression" in statement_walker:
        raise SystemExit("static-call traversal must not treat declaration and constructor type expressions as runtime code")
    if not all(fragment in module_ancestor for fragment in (
            'returntrueifancestor==""orancestor==module_path',
            "module_path[0:ancestor.len]!=ancestor",
            "module_path[ancestor.len]==58andmodule_path[ancestor.len+1.usize()]==58")):
        raise SystemExit("static-call visibility must reject sibling module paths while allowing lexical ancestors")
    if not all(fragment in walker for fragment in (
            "Decl.Module(module_name,module_body,module_line)",
            "nested_module:sview@source=module_name",
            "Decl.Scoped(scoped_body,scoped_line)",
            "forparameterinparameters|table|->table",
            "parameter.has_default",
            "parameter.default_value",
            "static_call_check_expression(file,parameter.default_value,static_fns,current_module,table)",
            "member.has_default",
            "member.default_value",
            "static_call_check_expression(file,member.default_value,static_fns,current_module,table)",
            "Decl.Struct(struct_name,members,affinity,has_named_states,has_derive,invariants,struct_position)",
            "check_static_call_context_walk(file,module_body,static_fns,nested_module,table)",
            "check_static_call_context_walk(file,scoped_body,static_fns,current_module,table)",
            "static_call_scope_is_inactive(file,scoped_line,current_module,table)",
            "static_call_check_statements(file,body,static_fns,current_module,table)",
            "is_static_function_declaration(static_fns,function_name,function_position,current_module)")) or \
            'static_fns.push(annotation)ifannotation.owner=="__static_fn"' not in entrypoint or \
            "check_static_call_context_walk(file,file.top_decls,static_fns,\"\",table)" not in entrypoint:
        raise SystemExit("static-call walker must carry lexical module identity through modules and scoped declarations")
    fixture = STATIC_CALL_CONTEXT_FIXTURE.read_text()
    smoke = STATIC_CALL_CONTEXT_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "module Compile:",
            "static def parse()",
            "module Runtime:",
            "static def helper()",
            "def parse()",
            "return helper()",
            "def caller()",
            "return parse()",
            "module Outer:",
            "static def ancestor_helper()",
            "module Inner:",
            "return ancestor_helper()",
            "static def shadowed_helper()",
            "module RuntimeShadow:",
            "def shadowed_helper()",
            "return shadowed_helper()",
            "module NestedCalls:",
            "static def hidden()",
            "def comprehension()",
            "return [hidden() for item in 0..<1]",
            "def matched()",
            "return match 0:",
            "def loop_iterable()",
            "for item in [hidden()]:",
            "def indexed()",
            "return [1][hidden().usize()]",
            "def constructed()",
            "return Box{value: hidden()}",
            "value: i64 = hidden()",
            "def with_default(value: i64 = hidden())",
            "return with_default()",
            "def asserted()",
            "assert hidden() == 9",
            "return Box{}",
            "module BranchSelection:",
            "static if false:",
            "static def branch_pick()",
            "static else:",
            "def branch_pick()",
            "return branch_pick()",
            "module UnknownRuntimeShadow:",
            "static def compile_only()",
            "static def late_bound()",
            "static if ELISA_TARGET_OS_WASI:",
            "def late_bound()",
            "return late_bound() + compile_only()",
            "module MixedOverloads:",
            "static def choose(value: i64)",
            "def choose(value: f64)",
            "return choose(1.5)")) or not all(fragment in smoke for fragment in (
            "static_call_context_module_identity.elisa",
            'static function "helper" can only be called from a static context',
            'static function "hidden" can only be called from a static context',
            '[[ "$hidden_count" -eq 8 ]]',
            'static function "parse" can only be called from a static context',
            'static function "ancestor_helper" can only be called from a static context',
            'static function "branch_pick" can only be called from a static context',
            'static function "branch_static" can only be called from a static context',
            'static function "shadowed_helper" can only be called from a static context',
            'ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown',
            'static function "compile_only" can only be called from a static context',
            'static function "late_bound" can only be called from a static context',
            'static function "choose" can only be called from a static context')):
        raise SystemExit("static-call regression must cover exact declaration, module, and active branch identity")
    lexical_fixture = LEXICAL_MODULE_FIXTURE.read_text()
    lexical_smoke = LEXICAL_MODULE_SMOKE.read_text()
    if not all(fragment in lexical_fixture for fragment in (
            "module Outer:",
            "const FEATURE: bool = true",
            "static if FEATURE:",
            "module Inner:",
            "const FEATURE: bool = false",
            "static def compile_time_helper()",
            "return compile_time_helper()")) or not all(fragment in lexical_smoke for fragment in (
            "static_if_condition_lexical_module.elisa",
            'static function "compile_time_helper" can only be called from a static context')):
        raise SystemExit("static-if module-provenance regression must distinguish Outer::FEATURE from Outer::Inner::FEATURE")


def require_policy_source() -> None:
    policy_text = compact(POLICY.read_text())
    declarations = (
        "constenumActionofu8:SkipSelectFallbackEvaluateCondition",
        "defrow_action(kind:StaticIfBranch::Kind,previously_satisfied:bool)->Action:",
        "ensurekind==StaticIfBranch::Kind.ChainHeadimpliesresult==Action.EvaluateCondition",
        "ensurekind==StaticIfBranch::Kind.ChainContinuationandnotpreviously_satisfiedimpliesresult==Action.EvaluateCondition",
        "ensurekind==StaticIfBranch::Kind.Fallbackandnotpreviously_satisfiedimpliesresult==Action.SelectFallback",
        "ensurepreviously_satisfiedandkind!=StaticIfBranch::Kind.ChainHeadimpliesresult==Action.Skip",
        "returnAction.Skipifpreviously_satisfiedandkind!=StaticIfBranch::Kind.ChainHead",
        "returnAction.EvaluateConditionifkind==StaticIfBranch::Kind.ChainHeadorkind==StaticIfBranch::Kind.ChainContinuation",
        "returnAction.SelectFallbackifkind==StaticIfBranch::Kind.Fallback",
        "returnAction.Skip",
        "defcondition_selects_branch(condition_ok:bool,condition_value:i64)->bool:",
        "returncondition_okandcondition_value!=StaticIfBranch::CONDITION_FALSE_VALUE",
    )
    if any(fragment not in policy_text for fragment in declarations):
        raise SystemExit("shared static-if policy must reset heads, skip satisfied chains, and match every row kind")
    if "kind==0" in policy_text or "kind==1" in policy_text or "kind==2" in policy_text:
        raise SystemExit("static-if policy reintroduced numeric branch tags")


def require_selector_layout() -> None:
    section = function_section(SELECTOR.read_text(), "selected_static_if_rows")
    section_code = source_code(section)
    body = compact(section_code)
    ordered_fragments = (
        "forrowin0..<file.static_if_lines.count|taken,satisfied_by_depth,file,structs|:",
        "branch_kind:StaticIfBranch::Kind=file.static_if_kinds[row]",
        "row_depth:usize=file.static_if_depths[row].usize()ifrow<file.static_if_depths.countelseStaticIfBranch::TOP_LEVEL_DEPTH.usize()",
        "whilesatisfied_by_depth.count<=row_depth|satisfied_by_depth|:",
        "satisfied_by_depth.push(false)",
        "starts_new_chain:bool=matchbranch_kind:StaticIfBranch::Kind.ChainHead:true_:false",
        "satisfied_by_depth[row_depth]<-falseifstarts_new_chain",
        "action:StaticIfPolicy::Action=StaticIfPolicy::row_action(branch_kind,satisfied_by_depth[row_depth])",
        "matchaction:",
        "condition_ok:mutablebool=row<file.static_if_conds.countandrow<file.static_if_modules.count",
        "condition_value:mutablei64=0",
        "ifcondition_ok:",
        "previous_owner:sview=structs.visibility.current_owner",
        "structs.visibility.current_owner<-file.static_if_modules[row]",
        "condition_value<-fold_const_expr(file.static_if_conds[row],structs,condition_ok)",
        "structs.visibility.current_owner<-previous_owner",
        "continueifnotStaticIfPolicy::condition_selects_branch(condition_ok,condition_value)",
    )
    positions = [body.find(fragment) for fragment in ordered_fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("static-if selector no longer resets each chain at its own depth before applying policy")
    if body.count("taken.push(row.u32())") != 2:
        raise SystemExit("fallback and true-condition arms must each append their selected row identity")
    if body.count("satisfied_by_depth[row_depth]<-true") != 2:
        raise SystemExit("both selected fallback and selected condition arms must satisfy only their depth")
    lines = section_code.splitlines()
    loop_index = next((index for index, line in enumerate(lines)
                       if "for row in 0..<file.static_if_lines.count" in line), None)
    if loop_index is None:
        raise SystemExit("static-if source-order row loop is missing")
    loop_indent = len(lines[loop_index]) - len(lines[loop_index].lstrip(" \t"))
    expected_loop_children = [
        "branch_kind: StaticIfBranch::Kind = file.static_if_kinds[row]",
        "row_depth: usize = file.static_if_depths[row].usize() if row < file.static_if_depths.count else StaticIfBranch::TOP_LEVEL_DEPTH.usize()",
        "while satisfied_by_depth.count <= row_depth |satisfied_by_depth|:",
        "starts_new_chain: bool = match branch_kind:",
        "satisfied_by_depth[row_depth] <- false if starts_new_chain",
        "action: StaticIfPolicy::Action = StaticIfPolicy::row_action(branch_kind, satisfied_by_depth[row_depth])",
        "match action:",
    ]
    if direct_children(lines, loop_index, loop_indent) != expected_loop_children:
        raise SystemExit("depth growth, chain reset, policy call, and action match must be direct row-loop steps")
    action_index = next((index for index, line in enumerate(lines)
                         if line.strip() == "match action:"), None)
    if action_index is None:
        raise SystemExit("static-if action match is missing")
    action_indent = len(lines[action_index]) - len(lines[action_index].lstrip(" \t"))
    expected_arms = [
        "StaticIfPolicy::Action::Skip:",
        "StaticIfPolicy::Action::SelectFallback:",
        "StaticIfPolicy::Action::EvaluateCondition:",
    ]
    if direct_children(lines, action_index, action_indent) != expected_arms:
        raise SystemExit("static-if action match must handle skip, fallback, and condition evaluation explicitly")
    arm_children = {}
    for arm in expected_arms:
        arm_index = next(index for index, line in enumerate(lines) if line.strip() == arm)
        arm_indent = len(lines[arm_index]) - len(lines[arm_index].lstrip(" \t"))
        arm_children[arm] = direct_children(lines, arm_index, arm_indent)
    if arm_children[expected_arms[0]] != ["continue"]:
        raise SystemExit("a previously satisfied static-if chain must continue to the next source row")
    if arm_children[expected_arms[1]] != [
        "taken.push(row.u32())",
        "satisfied_by_depth[row_depth] <- true",
    ]:
        raise SystemExit("fallback selection must append its own line and satisfy only its depth without folding")
    if arm_children[expected_arms[2]] != [
        "condition_ok: mutable bool = row < file.static_if_conds.count and row < file.static_if_modules.count",
        "condition_value: mutable i64 = 0",
        "if condition_ok:",
        "continue if not StaticIfPolicy::condition_selects_branch(condition_ok, condition_value)",
        "taken.push(row.u32())",
        "satisfied_by_depth[row_depth] <- true",
    ]:
        raise SystemExit("condition branches must decline missing metadata and update selection only after a row-module fold")
    fold_index = next((index for index, line in enumerate(lines)
                       if line.strip() == "if condition_ok:"), None)
    if fold_index is None:
        raise SystemExit("condition fold guard is missing")
    fold_indent = len(lines[fold_index]) - len(lines[fold_index].lstrip(" \t"))
    if direct_children(lines, fold_index, fold_indent) != [
        "previous_owner: sview = structs.visibility.current_owner",
        "structs.visibility.current_owner <- file.static_if_modules[row]",
        "condition_value <- fold_const_expr(file.static_if_conds[row], structs, condition_ok)",
        "structs.visibility.current_owner <- previous_owner",
    ]:
        raise SystemExit("static-if condition folding must restore the prior owner after using the row's lexical module")


def require_backend_position_identity() -> None:
    selector = compact(SELECTOR.read_text())
    module = compact(function_section(CODEGEN_MODULE.read_text(), "select_module_declarations"))
    statement_backend = compact(CODEGEN_STMT.read_text())
    backend_annotations = compact(CODEGEN_TABLE.read_text())
    unsafe = compact(DRIVER_UNSAFE.read_text())
    unsafe_segments = compact(DRIVER_UNSAFE_SEGMENTS.read_text())
    impl_registration = compact(function_section(CODEGEN_DECL_HOISTING.read_text(), "record_impl_member_lines"))
    impl_parser = compact(function_section(PARSER_DECL_IMPL.read_text(), "impl_declaration"))
    condition_check = compact(function_section(STATIC_IF_CONDITION.read_text(), "check_static_if_condition"))
    condition_owner_walk = compact(function_section(STATIC_IF_CONDITION.read_text(), "static_if_mark_statement_owners"))
    function_owner_walk = compact(function_section(STATIC_IF_CONDITION.read_text(), "static_if_collect_function_owners"))
    pipeline = compact(FULL_PIPELINE.read_text())
    ast_condition = compact(function_section(DRIVER_AST_DECL.read_text(), "emit_ast_static_condition"))
    selected_offsets = compact(function_section(SELECTOR.read_text(), "selected_static_if_offsets"))
    if not all(fragment in selected_offsets for fragment in (
            "selected_static_if_rows(file,structs)",
            "row.usize()>=file.static_if_offsets.count",
            "taken_offsets.push(file.static_if_offsets[row.usize()])")) or not all(fragment in selector for fragment in (
            "flatten_static_branches[@r](decls:darray[Decl]&,branch_offsets:darray[u32]&,taken_offsets:darray[u32]&",
            "static_branch_is_taken(branch_offsets,scoped_line.offset)",
            "static_branch_is_taken(taken_offsets,scoped_line.offset)",
            "taken_offset==offset",
            "flatten_static_branches(module_body,branch_offsets,taken_offsets,flattened_members)")):
        raise SystemExit("backend declaration flattening must select static branches by exact source offsets")
    if not all(fragment in module for fragment in (
            "static_branch_offsets:darray[u32]=file.static_if_offsets",
            "selected_static_if_offsets(file,structs)",
            "flatten_static_branches(file.top_decls,static_branch_offsets,round_taken_offsets,round_top)",
            "structs.annotations.static_branch_offsets<-file.static_if_offsets",
            "structs.annotations.static_taken_offsets<-structs.annotations.static_taken_offsets.push(file.static_if_offsets[selected_row.usize()])")) or not all(fragment in backend_annotations for fragment in (
            "static_branch_lines:mutabledarray[u32]=[]",
            "static_branch_offsets:mutabledarray[u32]=[]",
            "static_taken_lines:mutabledarray[u32]=[]",
            "static_taken_offsets:mutabledarray[u32]=[]")):
        raise SystemExit("backend annotations must preserve diagnostic lines while carrying exact branch and selection offsets")
    if not all(fragment in statement_backend for fragment in (
            "static_branch_is_taken(structs.annotations.static_branch_offsets,block_line.offset)",
            "static_branch_is_taken(structs.annotations.static_taken_offsets,block_line.offset)")):
        raise SystemExit("runtime statement codegen must use branch offsets to distinguish same-line static blocks")
    if not all(fragment in impl_registration for fragment in (
            "annotation.owner==\"__impl_scope\"",
            "annotation.owner==\"__impl_concrete\"",
            "annotation.owner==\"__ext_concrete\"",
            "annotation.line==scoped_line.line",
            "annotation.offset==scoped_line.offset")) or not all(fragment in impl_parser for fragment in (
            'owner:"__impl_scope"',
            'owner:"__impl_concrete"',
            'owner:"__ext_concrete"',
            "offset:head.start")):
        raise SystemExit("impl metadata must carry and match the exact scoped declaration position")
    if not all(fragment in unsafe for fragment in (
            "unsafe_static_offset_is_taken(taken_offsets:darray[u32]&,offset:u32)",
            "us_b_line.offset",
            "static_taken_offsets:darray[u32]&")) or \
            "Backend::selected_static_offsets_for_report(file)" not in unsafe_segments:
        raise SystemExit("unsafe reporting must select statement branches by source offset too")
    if not all(fragment in condition_owner_walk for fragment in (
            'kind=="static"',
            "file.static_if_lines[row]==position.line",
            "file.static_if_offsets[row]==position.offset",
            "row_owner_offsets[row]<-function_offset",
            "row_owner_found[row]<-true",
            "static_if_mark_statement_owners(body,function_offset,file,row_owner_offsets,row_owner_found)")) or not all(fragment in function_owner_walk for fragment in (
            "position.offset",
            "static_if_mark_statement_owners(body,position.offset,file,row_owner_offsets,row_owner_found)",
            "static_if_collect_function_owners(module_body,file,row_owner_offsets,row_owner_found,param_owner_offsets,param_names)",
            "static_if_collect_function_owners(scoped_body,file,row_owner_offsets,row_owner_found,param_owner_offsets,param_names)")) or not all(fragment in condition_check for fragment in (
            "static_if_offsets:darray[u32]&",
            "row>=static_if_offsets.count",
            "static_if_lines[row]",
            "notrow_owner_found[row]",
            "row_owner_offsets[row]")) or \
            "file.static_if_conds,file.static_if_lines,file.static_if_offsets,file.static_if_kinds" not in pipeline or not all(fragment in ast_condition for fragment in (
            "file.static_if_offsets[condition_index]==branch_pos.offset",
            "file.static_if_lines[condition_index]==branch_pos.line")):
        raise SystemExit("semantic validation and AST output must use static branch offsets while retaining logical lines for diagnostics")
    fixture = BACKEND_ID_FIXTURE.read_text()
    smoke = STATIC_RUNTIME_SMOKE.read_text()
    if not all(fragment in fixture for fragment in (
            "#line 40 first-head.elisa",
            "static if true:",
            "def active_first()",
            "#line 40 second-head.elisa",
            "static if false:",
            "def inactive_second()",
            "def active_second()")) or not all(fragment in smoke for fragment in (
            "static_if_same_line_heads.elisa",
            "@active_first",
            "@active_second",
            "@inactive_second")):
        raise SystemExit("backend regression must exercise distinct conditional heads that share a #line value")


def require_static_if_callers() -> None:
    declaration = compact(function_section(PARSER_DECL_IMPL.read_text(), "static_if_declaration"))
    declaration_steps = (
        "matched_head:bool=parser.peek()==TokenKind.Iforparser.peek()==TokenKind.Elif",
        "is_chain_head:bool=parser.peek()==TokenKind.If",
        "parser<-parser.advance_if(matched_head)",
        "parser<-parser.capture_static_if_condition(head.line,head.start,is_chain_head)canGlobal{Read,Write}ifmatched_head",
        "parser<-parser.record_static_else(head.line,head.start)ifnotmatched_head",
        "parser<-parser.accept_if(TokenKind.Else,notmatched_head)",
        "parser.static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP",
        "parser<-parser.parse_scoped_block(out,head)canGlobal{Read,Write}",
        "parser.static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP",
        "has_continuation<-parser.peek()==TokenKind.Staticand(parser.peek_at(1)==TokenKind.Eliforparser.peek_at(1)==TokenKind.Else)",
    )
    positions = [declaration.find(fragment) for fragment in declaration_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("declaration static-if caller must classify head/continuation/fallback and bracket nested depth")
    statement = compact(function_section(PARSER_STMT.read_text(), "statement_inner"))
    statement_steps = (
        "ifkind==TokenKind.Static:",
        "ifparser.peek_at(1)==TokenKind.Iforparser.peek_at(1)==TokenKind.Eliforparser.peek_at(1)==TokenKind.Else:",
        "static_chain_head:bool=parser.peek()==TokenKind.If",
        "static_matched_head:bool=parser.peek()==TokenKind.Iforparser.peek()==TokenKind.Elif",
        "parser<-parser.advance_if(static_matched_head)",
        "parser<-parser.capture_static_if_condition(static_head.line,static_head.start,static_chain_head)canGlobal{Read,Write}ifstatic_matched_head",
        "parser<-parser.record_static_else(static_head.line,static_head.start)ifnotstatic_matched_head",
        "parser<-parser.accept_if(TokenKind.Else,notstatic_matched_head)",
        "parser.static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP",
        "parser=parser.parse_block()",
        "parser.static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP",
    )
    positions = [statement.find(fragment) for fragment in statement_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("statement static-if caller must classify its branch and bracket the parsed nested depth")
    for source, name in ((declaration, "declaration"), (statement, "statement")):
        if source.count("parser.static_if_depth<-parser.static_if_depth+StaticIfBranch::NESTING_LEVEL_STEP") != 1:
            raise SystemExit(f"{name} static-if caller must increment its nesting depth once")
        if source.count("parser.static_if_depth<-parser.static_if_depth-StaticIfBranch::NESTING_LEVEL_STEP") != 1:
            raise SystemExit(f"{name} static-if caller must decrement its nesting depth once")


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_proof_shapes() -> None:
    if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
        raise SystemExit("static-if proof declaration inventory changed")
    if 'include "../../src/parser/static_if_branch.elisa"' not in POSITIVE.read_text():
        raise SystemExit("positive proof must include the parser's exact branch-tag source")
    if 'include "../../src/backend/codegen_static_if_policy.elisa"' not in POSITIVE.read_text():
        raise SystemExit("positive proof must include the backend's exact policy source")
    if POSITIVE.read_text().splitlines()[:3] != [
        "# Proofs include and verify the exact branch policy consumed by the backend.",
        'include "../../src/parser/static_if_branch.elisa"',
        'include "../../src/backend/codegen_static_if_policy.elisa"',
    ]:
        raise SystemExit("positive proof source-link includes must remain first and direct")


require_branch_kind_contract()
require_parser_emission()
require_static_if_row_alignment()
require_backend_position_identity()
require_static_runtime_block_identity()
require_static_function_filter_identity()
require_static_call_context_identity()
require_policy_source()
require_selector_layout()
require_static_if_callers()
require_proof_shapes()

if ARGS.source_only:
    print("source_bound=True parser_rows=6 static_if_policy=True selector=True offsets=True modules=True")
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("static-if policy proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    BRANCH_TAGS,
    PARSER_FACADE,
    PARSER_CORE,
    PARSER_CORE_MEMBER_TABLES,
    PARSER_TOKENS,
    PARSER_DECL,
    PARSER_DECL_MODULE,
    PARSER_DECL_IMPL,
    PARSER_STMT,
    PARSER_TYPES_ENTRY,
    BACKEND_FACADE,
    CODEGEN_MODULE,
    CODEGEN_STMT,
    CODEGEN_TABLE,
    CODEGEN_DECL_HOISTING,
    MEXT,
    FILE_VIEW,
    STATIC_IF_CONDITION,
    FULL_PIPELINE,
    DRIVER_AST_DECL,
    MANUAL_FILE_LITERAL,
    POLICY,
    SELECTOR,
    DRIVER_UNSAFE,
    DRIVER_UNSAFE_SEGMENTS,
    STATIC_RUNTIME,
    STATIC_RUNTIME_FIXTURE,
    STATIC_RUNTIME_NESTED_FIXTURE,
    STATIC_RUNTIME_INACTIVE_FIXTURE,
    STATIC_RUNTIME_SIBLING_FIXTURE,
    STATIC_RUNTIME_SMOKE,
    STATIC_FN_FILTER_FIXTURE,
    STATIC_FN_FILTER_SMOKE,
    STATIC_CALL_CONTEXT,
    STATIC_CALL_CONTEXT_FIXTURE,
    STATIC_CALL_CONTEXT_SMOKE,
    LEXICAL_MODULE_FIXTURE,
    LEXICAL_MODULE_SMOKE,
    TRY_FALLIBLE,
    BACKEND_ID_FIXTURE,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_PROCESS_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES
assert not positive["findings"]

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "source-linked static-if kind/action policy, fold-failure behavior, and depth-local chain reset",
    "positive_declarations": sorted(POSITIVE_NAMES),
    "negative_controls_refused": sorted(NEGATIVE_NAMES),
    "replayed_certificates": positive["replay"]["replayed"],
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
