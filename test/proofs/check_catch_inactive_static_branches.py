"""Bind Catch static-branch filtering to the AST walkers and regression fixture."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
OUT_OF_SET = (ROOT / "src/semantic/check_catch_out_of_set.elisa").read_text()
PARAM_BINDER = (ROOT / "src/semantic/check_catch_param_binder.elisa").read_text()
ARM_VARIANT = (ROOT / "src/semantic/check_catch_arm_variant.elisa").read_text()
CATCH_EXHAUSTIVE = (ROOT / "src/semantic/check_catch_exhaustive.elisa").read_text()
PARALLEL_PASSES = (ROOT / "src/semantic/semantic_parallel_passes.elisa").read_text()
PARSER_STATEMENT = (ROOT / "src/parser/parser_stmt_pattern_arms.elisa").read_text()
PARSER_EXPRESSION = (ROOT / "src/parser/parser_expr.elisa").read_text()
PARSER_PRIMARY = (ROOT / "src/parser/parser_expr_primary.elisa").read_text()
PARSER_POSTFIX = (ROOT / "src/parser/parser_expr_postfix.elisa").read_text()
PARSER_BINARY = (ROOT / "src/parser/parser_expr_binary.elisa").read_text()
PARSER_LITERALS = (ROOT / "src/parser/parser_expr_literals.elisa").read_text()
FIXTURE = (ROOT / "test/repro/catch_inactive_static_branches.elisa").read_text()
UNKNOWN_FIXTURE = (ROOT / "test/repro/catch_unknown_static_branches.elisa").read_text()
SMOKE = (ROOT / "test/parity/catch_inactive_static_branches_smoke.sh").read_text()
UNKNOWN_SMOKE = (ROOT / "test/parity/catch_unknown_static_branches_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


for source, helper in (
    (OUT_OF_SET, "cos_static_if_branch_selection"),
    (PARAM_BINDER, "cpb_static_if_branch_selection"),
    (ARM_VARIANT, "cav_static_if_branch_selection"),
):
    branch_selection = function_source(source, helper)
    if not all(fragment in branch_selection for fragment in (
        "file.static_if_lines[row] != line",
        "file.static_if_offsets[row] != offset",
        "ewr_static_if_row_selection(file, found_row, lexical_module, table)",
        "return (false, false) if found_count > 1.usize()",
    )):
        raise SystemExit(f"{helper} must select by exact branch position and fail conservatively")

cos_stmts = function_source(OUT_OF_SET, "cos_walk_stmts")
cos_decls = function_source(OUT_OF_SET, "cos_walk_declarations")
cpb_stmts = function_source(PARAM_BINDER, "cpb_check_statements")
cpb_decls = function_source(PARAM_BINDER, "cpb_check_declarations")
cav_stmts = function_source(ARM_VARIANT, "cav_walk_statements")
cav_decls = function_source(ARM_VARIANT, "cav_walk_declarations")
for source, owner, branch_variant, selector in (
    (cos_stmts, "Stmt.Block", "block_line", "cos_static_if_branch_selection"),
    (cos_decls, "Decl.Scoped", "scoped_line", "cos_static_if_branch_selection"),
    (cpb_stmts, "Stmt.Block", "block_line", "cpb_static_if_branch_selection"),
    (cpb_decls, "Decl.Scoped", "scoped_line", "cpb_static_if_branch_selection"),
    (cav_stmts, "Stmt.Block", "line", "cav_static_if_branch_selection"),
    (cav_decls, "Decl.Scoped", "line", "cav_static_if_branch_selection"),
):
    if owner not in source or f"{selector}(file, {branch_variant}.line, {branch_variant}.offset" not in source or "if not branch.known or branch.selected" not in source:
        raise SystemExit(f"{owner} walker must skip only proven-inactive branches")

if "cos_walk_expression(expression, lexical_module, annotations, file, table)" not in cos_stmts:
    raise SystemExit("expression traversal must retain file static-if metadata")
if "check_catch_arm_variant(loop_view, table)" not in PARALLEL_PASSES or "file.top_decls, file, table" not in function_source(ARM_VARIANT, "check_catch_arm_variant"):
    raise SystemExit("catch variant walk must receive the full file and its static-if metadata")
catch_branch = function_source(CATCH_EXHAUSTIVE, "catch_annotation_branch_selection")
active_annotations = function_source(CATCH_EXHAUSTIVE, "catch_active_alias_annotations")
catch_entry = function_source(CATCH_EXHAUSTIVE, "check_catch_exhaustive")
if not all(fragment in catch_branch for fragment in (
    '"__catch_expr_static_branch"',
    '"__catch_arm_tail_static_branch"',
    'marker.owner != "__static_if_branch"',
    "marker.module != annotation.module or marker.line != annotation.line or marker.offset != annotation.offset",
    "marker.identity_id.usize()",
    "marker.identity_id == 4294967295 or not branch.known",
    "return (false, false) if found_marker and unknown",
)) or not all(fragment in active_annotations for fragment in (
    'annotation.name == "__catch_expr" or annotation.name == "__catch_arm_tail"',
    "continue if branch.known and not branch.selected",
)) or "annotations: mutable darray[Ast::EnumAnnotation] = catch_active_alias_annotations(file, table)" not in catch_entry:
    raise SystemExit("Catch annotation diagnostics must drop proven-inactive markers and retain unknown ones")
if not all(fragment in PARSER_STATEMENT for fragment in (
    'record_static_if_branch_rows("__catch_expr_static_branch", catch_callee, catch_token)',
)) or 'record_static_if_branch_rows("__catch_expr_static_branch", callee_name, token)' not in PARSER_EXPRESSION:
    raise SystemExit("parser must attach exact branch provenance to both Catch forms and assignment tails")
catch_expression = function_source(PARSER_EXPRESSION, "primary_catch_expression")
keyword_expression = function_source(PARSER_EXPRESSION, "primary_keyword_expression")
primary_expression = function_source(PARSER_PRIMARY, "primary_expression")
postfix_expression = function_source(PARSER_POSTFIX, "postfix_expression")
unary_expression = function_source(PARSER_BINARY, "unary_expression")
binary_step = function_source(PARSER_BINARY, "binary_expression_step")
binary_level = function_source(PARSER_BINARY, "binary_expression_at_level")
expression_entry = function_source(PARSER_LITERALS, "expression")
expression_body_if = function_source(PARSER_LITERALS, "expression_body_if")
expression_body = function_source(PARSER_LITERALS, "expression_body")
if not all(fragment in catch_expression for fragment in (
    "can Memory.Allocate, Abort.Panic:",
    'record_static_if_branch_rows("__catch_expr_static_branch", callee_name, token)',
)) or "can Memory.Allocate, Abort.Panic:" not in primary_expression or \
        "can Memory.Allocate, Abort.Panic:" not in postfix_expression or \
        "can Memory.Allocate, Abort.Panic:" not in unary_expression or \
        "can Memory.Allocate, Abort.Panic:" not in binary_step or \
        "can Memory.Allocate, Abort.Panic:" not in binary_level or \
        "can Memory.Allocate, Abort.Panic:" not in expression_body or \
        'primary_catch_expression(token) can Global{Read,Write}, Memory.Allocate' not in keyword_expression or \
        'primary_keyword_expression(kind, token) can Global{Read,Write}, Memory.Allocate' not in primary_expression or \
        'primary_expression() can Global{Read,Write}, Memory.Allocate' not in postfix_expression or \
        'postfix_expression() can Global{Read,Write}, Memory.Allocate' not in unary_expression or \
        'unary_expression() can Global{Read,Write}, Memory.Allocate' not in unary_expression or \
        'unary_expression() can Global{Read,Write}, Memory.Allocate' not in expression_body or \
        'unary_expression() can Global{Read,Write}, Memory.Allocate' not in binary_step or \
        'binary_expression_at_level(membership_right, 4) can Global{Read,Write}, Memory.Allocate' not in binary_step or \
        'binary_expression_at_level(right, current_precedence + 1) can Global{Read,Write}, Memory.Allocate' not in binary_step or \
        'binary_expression_step(active, minimum_precedence) can Global{Read,Write}, Memory.Allocate' not in binary_level or \
        'expression_body() can Global{Read,Write}, Memory.Allocate' not in expression_body_if or \
        'expression_body_if(not exceeded) can Global{Read,Write}, Memory.Allocate' not in expression_entry or \
        PARSER_EXPRESSION.count('parser.postfix_expression() can Global{Read,Write}, Memory.Allocate') < 2 or \
        'parser.postfix_expression() can Global{Read,Write}, Memory.Allocate' not in PARSER_BINARY:
    raise SystemExit("expression Catch must carry the branch-row recorder's allocation effect through the primary parser path")
if any('unary_expression() can Global{Read,Write}' in parser_file.read_text()
       for parser_file in (ROOT / "src/parser").glob("*.elisa")):
    raise SystemExit("all parser unary-expression entrypoints must grant the Catch branch recorder's allocation effect")
if any("binary_expression_at_level(" in line and "def binary_expression_at_level(" not in line and
       "can Global{Read,Write}, Memory.Allocate" not in line
       for parser_file in (ROOT / "src/parser").glob("*.elisa") for line in parser_file.read_text().splitlines()):
    raise SystemExit("all parser binary-expression entrypoints must grant the Catch branch recorder's allocation effect")
catch_tail = function_source(PARSER_STATEMENT, "record_catch_tail")
if not all(fragment in catch_tail for fragment in (
    'name: "__catch_arm_tail"',
    "offset: catch_token.start",
    "module: parser.current_module",
    'record_static_if_branch_rows("__catch_arm_tail_static_branch", "__catch_arm_tail", catch_token)',
)):
    raise SystemExit("catch-tail rows must carry the branch marker's exact position and module")
if not all(fragment in FIXTURE for fragment in (
    "static if false:",
    "inactive_declaration_out_of_set",
    "inactive_declaration_param",
    "inactive_statement_out_of_set",
    "inactive_statement_param",
    "Fault.Other",
    "Phantom.Gone",
    "plain:",
)) or not all(fragment in SMOKE for fragment in (
    "catch_inactive_static_branches.elisa",
    "grep -q '^D 0$'",
)):
    raise SystemExit("inactive declaration and statement Catch repro coverage is incomplete")
if not all(fragment in UNKNOWN_FIXTURE for fragment in (
    "ELISA_TARGET_OS_WASI",
    "static if true:",
    "active_tail_control",
    "all_faults",
    "unknown_statement_out_of_set",
    "Fault.Other",
    "unknown_statement_param",
    "plain:",
)) or not all(fragment in UNKNOWN_SMOKE for fragment in (
    "catch_unknown_static_branches.elisa",
    'catch arm "Fault.Other" does not match the caught call',
    'catch arm "Phantom.Gone" does not match the caught call',
    'catch arm "plain" does not match R',
    "match expression arm must end with an expression",
)):
    raise SystemExit("unknown static branches must retain conservative Catch diagnostics")

print("Catch inactive static-branch source binding passed")
