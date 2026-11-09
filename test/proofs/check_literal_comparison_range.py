"""Admit source-linked proofs of integer literal comparison range checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure
from literal_comparison_source import (
    compact,
    compact_code,
    function_section,
    enum_variant_names,
    explicit_match_arm_names,
    direct_child,
    edge_parts,
    wrap_direct_child_block,
    validate_edge_set,
    validate_or_theorem,
    struct_fields,
    EXPECTED_EXPR_NAMES,
    EXPECTED_STMT_NAMES,
    EXPECTED_DECL_NAMES,
    EXPECTED_SIDE_TABLE_FIELDS,
    STATEMENT_EDGES,
    DECLARATION_EDGES,
    EXPRESSION_PROOF_ROUTES,
    EXPRESSION_PROOF_THEOREMS,
    STATEMENT_PROOF_ROUTES,
    DECLARATION_PROOF_ROUTES,
    EXPRESSION_EDGES,
)


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
HELPER = ROOT / "src/semantic/literal_comparison_range.elisa"
CONSUMER = ROOT / "src/semantic/check_literal_comparison_impossible.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
EFFECT_TYPE_SHAPE = ROOT / "src/parser/effect_type_shape.elisa"
POSITIVE = HERE / "literal_comparison_range.elisa"
NEGATIVE = HERE / "literal_comparison_range_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROOF_TIMEOUT_SECONDS = 120

if not __debug__:
    raise SystemExit("run without Python -O")


def match_blocks(text: str, variable: str) -> list[list[str]]:
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if not re.search(rf"\bwhen {re.escape(variable)}:$", line.strip()):
            continue
        base_indent = len(line) - len(line.lstrip())
        arms = []
        for arm in lines[index + 1:]:
            if not arm.strip():
                continue
            indent = len(arm) - len(arm.lstrip())
            if indent <= base_indent:
                break
            if indent != base_indent + 4:
                raise SystemExit("range match contains a nested or malformed arm")
            arms.append(arm.strip())
        blocks.append(arms)
    return blocks


type_arms = [
    '"u8" | "u16" | "u32" | "i8" | "i16" | "i32" -> true',
    "_ -> false",
]
range_arms = [
    '"u8" -> value < U8_MIN or value > U8_MAX',
    '"u16" -> value < U16_MIN or value > U16_MAX',
    '"u32" -> value < U32_MIN or value > U32_MAX',
    '"i8" -> value < I8_MIN or value > I8_MAX',
    '"i16" -> value < I16_MIN or value > I16_MAX',
    '"i32" -> value < I32_MIN or value > I32_MAX',
    "_ -> false",
]
constant_values = {
    "U8_MIN": "0",
    "U8_MAX": "255",
    "U16_MIN": "0",
    "U16_MAX": "65535",
    "U32_MIN": "0",
    "U32_MAX": "4294967295",
    "I8_MIN": "-128",
    "I8_MAX": "127",
    "I16_MIN": "-32768",
    "I16_MAX": "32767",
    "I32_MIN": "-2147483648",
    "I32_MAX": "2147483647",
}


def validate_helper(text: str) -> None:
    if match_blocks(function_section(text, "is_supported_integer_type"), "type_name") != [type_arms] * 2:
        raise SystemExit("supported integer type classifier differs from its closed match")
    if match_blocks(function_section(text, "is_outside"), "type_name") != [range_arms] * 2:
        raise SystemExit("integer range classifier differs from its named endpoint matches")
    for name, value in constant_values.items():
        declaration = rf"(?m)^\s*const {name}: i64 = {re.escape(value)}$"
        if len(re.findall(declaration, text)) != 1:
            raise SystemExit(f"range endpoint constant {name} changed")


helper_text = HELPER.read_text()
validate_helper(helper_text)
consumer_text = CONSUMER.read_text()
ast_text = AST_NODES.read_text()
side_table_text = AST_SIDE_TABLES.read_text()
effect_shape_text = EFFECT_TYPE_SHAPE.read_text()
if enum_variant_names(ast_text, "Expr", "Stmt") != EXPECTED_EXPR_NAMES:
    raise SystemExit("expression AST variants changed without extending the literal-comparison walk proof")
if enum_variant_names(ast_text, "Stmt", "Decl") != EXPECTED_STMT_NAMES:
    raise SystemExit("statement AST variants changed without extending the literal-comparison walk proof")
if enum_variant_names(ast_text, "Decl", "Pattern") != EXPECTED_DECL_NAMES:
    raise SystemExit("declaration AST variants changed without extending the literal-comparison walk proof")
expression_source = function_section(consumer_text, "walk_expression_for_literal_comparison")
statement_source = function_section(consumer_text, "walk_statements_for_literal_comparison")
declaration_source = function_section(consumer_text, "check_literal_comparison_declarations")
expression_arms = explicit_match_arm_names(expression_source, "match expression:", "Expr.")
if tuple(sorted(expression_arms)) != tuple(sorted(EXPECTED_EXPR_NAMES)):
    raise SystemExit("literal-comparison expression walk is not exhaustive over the AST variants")
statement_arms = explicit_match_arm_names(statement_source, "match statement:", "Stmt.")
if tuple(sorted(statement_arms)) != tuple(sorted(EXPECTED_STMT_NAMES)):
    raise SystemExit("literal-comparison statement walk is not exhaustive over the AST variants")
declaration_arms = explicit_match_arm_names(declaration_source, "match declaration:", "Decl.")
if tuple(sorted(declaration_arms)) != tuple(sorted(EXPECTED_DECL_NAMES)):
    raise SystemExit("literal-comparison declaration walk is not exhaustive over the AST variants")
for record, expected_fields in EXPECTED_SIDE_TABLE_FIELDS.items():
    if struct_fields(side_table_text, record) != expected_fields:
        raise SystemExit(f"AST side-table record {record} changed without extending the walk proof")
validate_edge_set(expression_source, EXPRESSION_EDGES, "expression")
validate_edge_set(statement_source, STATEMENT_EDGES, "statement")
validate_edge_set(declaration_source, DECLARATION_EDGES, "declaration")
expected_effect_children = compact_code("""children: mutable darray[Expr] = []
for candidate in candidates |children|:
    children.extend(candidate.captures)
children.extend(arguments)
return children""")
if compact_code(function_section(effect_shape_text, "effect_runtime_children")) != expected_effect_children:
    raise SystemExit("static-effect runtime child projection no longer includes every capture and argument")
if 'include "./literal_comparison_range.elisa"' not in consumer_text:
    raise SystemExit("literal comparison checker no longer imports the proved range policy")
if "literal_outside_range(" in consumer_text or "def is_target_type(" in consumer_text:
    raise SystemExit("literal comparison consumer retains an unproved inline range helper")
consumer_compact = compact(consumer_text)
for sign_constant in (
    "const NEGATIVE_LITERAL_SIGN_FLAG: u32 = 1",
    "const NONNEGATIVE_LITERAL_SIGN_FLAG: u32 = 0",
):
    if consumer_compact.count(compact(sign_constant)) != 1:
        raise SystemExit("literal diagnostic sign flags must use their named encodings")
if "negative:u32=NEGATIVE_LITERAL_SIGN_FLAGifliteral.sign==\"-\"elseNONNEGATIVE_LITERAL_SIGN_FLAG" not in consumer_compact:
    raise SystemExit("literal diagnostic no longer encodes the sign with named constants")

comparison_impossible_body = compact_code("""can Abort.Panic:
    match literal_expr:
        Expr.IntLit(val, _):
            return LiteralComparisonRange::is_outside(type_name, val)
        Expr.Unary(TokenKind.Minus, Expr.IntLit(neg_val, _), _):
            return LiteralComparisonRange::is_outside(type_name, -neg_val)
        Expr.Paren(inner, _):
            return comparison_is_impossible(type_name, inner)
        _:
            return false""")
literal_magnitude_body = compact_code("""can Abort.Panic:
    match literal_expr:
        Expr.IntLit(val, _):
            return (true, val.u32(), "") if val >= 0
            return (true, (-val).u32(), "-")
        Expr.Unary(TokenKind.Minus, Expr.IntLit(neg_val, _), _):
            return (true, neg_val.u32(), "-") if neg_val >= 0
            return (true, (-neg_val).u32(), "")
        Expr.Paren(inner, _):
            return comparison_literal_magnitude(inner)
        _:
            return (false, 0, "")""")
report_literal_body = compact_code("""can Memory.Allocate, Abort.Panic:
    return if not LiteralComparisonRange::is_supported_integer_type(type_name) or not comparison_is_impossible(type_name, literal_expr)
    literal: (found: bool, magnitude: u32, sign: sview) = comparison_literal_magnitude(literal_expr)
    if literal.found:
        negative: u32 = NEGATIVE_LITERAL_SIGN_FLAG if literal.sign == "-" else NONNEGATIVE_LITERAL_SIGN_FLAG
        table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.LiteralAssignOutOfRange, name: "", line: line.line, pos: Ast::expr_pos(literal_expr), expected: type_name, actual: "", expected_count: literal.magnitude, actual_count: negative})
    else:
        table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.LiteralComparisonImpossible, name: "", line: line.line, pos: Ast::expr_pos(literal_expr), expected: type_name, actual: ""})""")


def validate_consumer(text: str) -> None:
    expected_bodies = {
        "comparison_is_impossible": comparison_impossible_body,
        "comparison_literal_magnitude": literal_magnitude_body,
        "report_literal_comparison": report_literal_body,
    }
    for name, expected in expected_bodies.items():
        if compact_code(function_section(text, name)) != expected:
            raise SystemExit(f"production {name} no longer follows the source-linked literal rule")


validate_consumer(consumer_text)
consumer_mutations = (
    consumer_text.replace(
        "return LiteralComparisonRange::is_outside(type_name, val)",
        "return false",
        1,
    ),
    consumer_text.replace(
        "return if not LiteralComparisonRange::is_supported_integer_type(type_name) or not comparison_is_impossible(type_name, literal_expr)",
        "return if false",
        1,
    ),
    consumer_text.replace('literal.sign == "-"', 'literal.sign == "+"', 1),
    consumer_text.replace('literal.sign == "-"', 'literal.sign == " -"', 1),
)
for mutated in consumer_mutations:
    if mutated == consumer_text:
        raise SystemExit("literal comparison consumer mutation did not change its source")
    try:
        validate_consumer(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("literal comparison consumer mutation escaped the source gate")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "../../src/semantic/literal_comparison_range.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production range policy")
if 'include "./parser_token_kind_projection.elisa"' not in positive_text:
    raise SystemExit("comparison outcome proofs no longer import the token-kind projection")
if 'include "../../src/semantic/comparison_operator_policy.elisa"' not in positive_text:
    raise SystemExit("comparison outcome proofs no longer import the production operator set")
if 'include "./literal_comparison_range.elisa"' not in negative_text:
    raise SystemExit("negative claims no longer challenge the source-linked proof")
proof_type_arms = [
    '"u8" | "u16" | "u32" | "i8" | "i16" | "i32" -> true',
    "_ -> false",
]
proof_range_arms = [
    '"u8" -> value < LiteralComparisonRange::U8_MIN or value > LiteralComparisonRange::U8_MAX',
    '"u16" -> value < LiteralComparisonRange::U16_MIN or value > LiteralComparisonRange::U16_MAX',
    '"u32" -> value < LiteralComparisonRange::U32_MIN or value > LiteralComparisonRange::U32_MAX',
    '"i8" -> value < LiteralComparisonRange::I8_MIN or value > LiteralComparisonRange::I8_MAX',
    '"i16" -> value < LiteralComparisonRange::I16_MIN or value > LiteralComparisonRange::I16_MAX',
    '"i32" -> value < LiteralComparisonRange::I32_MIN or value > LiteralComparisonRange::I32_MAX',
    "_ -> false",
]
if match_blocks(function_section(positive_text, "source_supported_types_match_the_closed_set"), "type_name") != [proof_type_arms]:
    raise SystemExit("proof no longer states the exact supported integer type set")
if match_blocks(function_section(positive_text, "source_range_rule_matches_each_type"), "type_name") != [proof_range_arms]:
    raise SystemExit("proof no longer states the exact named endpoint rules")
positive_names = {
    "source_supported_types_match_the_closed_set",
    "source_range_rule_matches_each_type",
    "all_integer_type_endpoints_are_inside",
    "adjacent_values_outside_each_range_are_rejected",
    "unsupported_type_names_are_never_outside",
    "upper_range_comparisons_are_constant",
    "lower_range_comparisons_are_constant",
    "u8_upper_boundary_comparisons_are_fixed",
    "i8_lower_boundary_comparisons_are_fixed",
    "proof_literal_comparison_match_children_reported",
    "proof_literal_comparison_catch_children_reported",
    "proof_literal_comparison_static_effect_children_reported",
    "proof_literal_comparison_unary_child_reported",
    "proof_literal_comparison_refinement_children_reported",
    "proof_literal_comparison_get_else_children_reported",
    "proof_literal_comparison_statement_children_reported",
    "proof_literal_comparison_declaration_children_reported",
}
negative_names = {
    "a_u8_maximum_is_outside",
    "an_i8_minimum_is_outside",
    "i64_is_a_supported_target_type",
    "an_u8_maximum_can_exceed_the_first_outside_value",
    "an_i8_minimum_can_be_less_than_the_first_outside_value",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")
for name, routes in EXPRESSION_PROOF_THEOREMS.items():
    validate_or_theorem(positive_text, name, routes, expression_source, EXPRESSION_EDGES, "expression")
effect_theorem_routes = EXPRESSION_PROOF_THEOREMS["proof_literal_comparison_static_effect_children_reported"]
if (tuple(effect_theorem_routes) != ("capture_reported", "argument_reported")
        or "children.extend(candidate.captures)" not in expected_effect_children
        or "children.extend(arguments)" not in expected_effect_children):
    raise SystemExit("static-effect proof inputs are not bound to capture and argument traversal")
validate_or_theorem(
    positive_text,
    "proof_literal_comparison_statement_children_reported",
    STATEMENT_PROOF_ROUTES,
    statement_source,
    STATEMENT_EDGES,
    "statement",
)
validate_or_theorem(
    positive_text,
    "proof_literal_comparison_declaration_children_reported",
    DECLARATION_PROOF_ROUTES,
    declaration_source,
    DECLARATION_EDGES,
    "declaration",
)
endpoint_body = compact(function_section(positive_text, "all_integer_type_endpoints_are_inside"))
adjacent_body = compact(function_section(positive_text, "adjacent_values_outside_each_range_are_rejected"))
if "ensureresult==truecanAbort.Panic:return(" not in endpoint_body:
    raise SystemExit("endpoint theorem no longer requires every endpoint to be accepted")
if "ensureresult==truecanAbort.Panic:return(" not in adjacent_body:
    raise SystemExit("adjacent-value theorem no longer requires every neighbor to be rejected")
for type_name in ("u8", "u16", "u32", "i8", "i16", "i32"):
    upper = type_name.upper()
    for edge in ("MIN", "MAX"):
        inside = f'notLiteralComparisonRange::is_outside("{type_name}",LiteralComparisonRange::{upper}_{edge})'
        if inside not in endpoint_body:
            raise SystemExit(f"endpoint proof is missing the {type_name} {edge.lower()} boundary")
    lower_neighbor = f'LiteralComparisonRange::is_outside("{type_name}",LiteralComparisonRange::{upper}_MIN-1)'
    upper_neighbor = f'LiteralComparisonRange::is_outside("{type_name}",LiteralComparisonRange::{upper}_MAX+1)'
    if lower_neighbor not in adjacent_body or upper_neighbor not in adjacent_body:
        raise SystemExit(f"adjacent-value proof is missing the {type_name} range neighbors")
unsupported_body = compact(function_section(positive_text, "unsupported_type_names_are_never_outside"))
if ("requiresnotLiteralComparisonRange::is_supported_integer_type(type_name)" not in unsupported_body
        or "ensureresult==true" not in unsupported_body
        or "returnnotLiteralComparisonRange::is_outside(type_name,value)" not in unsupported_body):
    raise SystemExit("unsupported-type theorem no longer states fail-closed behavior")

comparison_outcome_shapes = {
    "upper_range_comparisons_are_constant": compact("""requires value >= minimum
    requires value <= maximum
    requires literal > maximum
    requires ComparisonOperatorPolicy::is_comparison(operator)
    ensure result == true
    can Abort.Panic:
        return when operator:
            Lexer::TokenKind.EqEq -> not (value == literal)
            Lexer::TokenKind.BangEq -> value != literal
            Lexer::TokenKind.Lt -> value < literal
            Lexer::TokenKind.Gt -> not (value > literal)
            Lexer::TokenKind.LtEq -> value <= literal
            Lexer::TokenKind.GtEq -> not (value >= literal)
            _ -> false"""),
    "lower_range_comparisons_are_constant": compact("""requires value >= minimum
    requires value <= maximum
    requires literal < minimum
    requires ComparisonOperatorPolicy::is_comparison(operator)
    ensure result == true
    can Abort.Panic:
        return when operator:
            Lexer::TokenKind.EqEq -> not (value == literal)
            Lexer::TokenKind.BangEq -> value != literal
            Lexer::TokenKind.Lt -> not (value < literal)
            Lexer::TokenKind.Gt -> value > literal
            Lexer::TokenKind.LtEq -> not (value <= literal)
            Lexer::TokenKind.GtEq -> value >= literal
            _ -> false"""),
    "u8_upper_boundary_comparisons_are_fixed": compact("""ensure result == true
    can Abort.Panic:
        return (
            not (LiteralComparisonRange::U8_MAX == LiteralComparisonRange::U8_MAX + 1)
            and LiteralComparisonRange::U8_MAX != LiteralComparisonRange::U8_MAX + 1
            and LiteralComparisonRange::U8_MAX < LiteralComparisonRange::U8_MAX + 1
            and not (LiteralComparisonRange::U8_MAX > LiteralComparisonRange::U8_MAX + 1)
            and LiteralComparisonRange::U8_MAX <= LiteralComparisonRange::U8_MAX + 1
            and not (LiteralComparisonRange::U8_MAX >= LiteralComparisonRange::U8_MAX + 1)
        )"""),
    "i8_lower_boundary_comparisons_are_fixed": compact("""ensure result == true
    can Abort.Panic:
        return (
            not (LiteralComparisonRange::I8_MIN == LiteralComparisonRange::I8_MIN - 1)
            and LiteralComparisonRange::I8_MIN != LiteralComparisonRange::I8_MIN - 1
            and not (LiteralComparisonRange::I8_MIN < LiteralComparisonRange::I8_MIN - 1)
            and LiteralComparisonRange::I8_MIN > LiteralComparisonRange::I8_MIN - 1
            and not (LiteralComparisonRange::I8_MIN <= LiteralComparisonRange::I8_MIN - 1)
            and LiteralComparisonRange::I8_MIN >= LiteralComparisonRange::I8_MIN - 1
        )"""),
}
for name, expected in comparison_outcome_shapes.items():
    if compact_code(function_section(positive_text, name)) != expected:
        raise SystemExit(f"{name} no longer proves the fixed comparison outcomes outside a type interval")

# Tie the range proof to the production diagnostic path: only comparison operators
# reach the literal checks, and both operand orientations pass the literal to the
# same range-gated diagnostic helper before the expression walk continues.
binary_comparison_branch = compact("""Expr.Binary(left, operator, right, line):
    # Check for comparison operators: ==, !=, <, >, <=, >=
    is_comparison: bool = ComparisonOperatorPolicy::is_comparison(operator)
    # Try: left is Ident, right is literal (possibly wrapped)
    if is_comparison:
        match left:
            Expr.Ident(left_name, left_line):
                left_type: sview = local_type_of(var_types, type_names, left_name)
                table <- report_literal_comparison(left_type, right, line, table)
            _:
                # Try: right is Ident, left is literal (possibly wrapped).
                match right:
                    Expr.Ident(right_name, right_line):
                        right_type: sview = local_type_of(var_types, type_names, right_name)
                        table <- report_literal_comparison(right_type, left, line, table)
                    _:
                        pass
    # Recursively walk both sides
    table <- walk_expression_for_literal_comparison(left, table, var_types, type_names)
    table <- walk_expression_for_literal_comparison(right, table, var_types, type_names) if operator != TokenKind.Is and operator != TokenKind.As""")
walker = compact(function_section(consumer_text, "walk_expression_for_literal_comparison"))
if binary_comparison_branch not in walker:
    raise SystemExit("literal comparison diagnostics no longer follow the proved operator and range gate")
mutated_walker = consumer_text.replace("if is_comparison:", "if true:", 1)
if binary_comparison_branch in compact(function_section(mutated_walker, "walk_expression_for_literal_comparison")):
    raise SystemExit("literal comparison source gate accepted an unconditional diagnostic-branch mutation")
negative_shapes = {
    "a_u8_maximum_is_outside": 'ensureresult==truecanAbort.Panic:returnLiteralComparisonRange::is_outside("u8",LiteralComparisonRange::U8_MAX)',
    "an_i8_minimum_is_outside": 'ensureresult==truecanAbort.Panic:returnLiteralComparisonRange::is_outside("i8",LiteralComparisonRange::I8_MIN)',
    "i64_is_a_supported_target_type": 'ensureresult==truecanAbort.Panic:returnLiteralComparisonRange::is_supported_integer_type("i64")',
    "an_u8_maximum_can_exceed_the_first_outside_value": 'ensureresult==truecanAbort.Panic:returnLiteralComparisonRange::U8_MAX>LiteralComparisonRange::U8_MAX+1',
    "an_i8_minimum_can_be_less_than_the_first_outside_value": 'ensureresult==truecanAbort.Panic:returnLiteralComparisonRange::I8_MIN<LiteralComparisonRange::I8_MIN-1',
}
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges the intended range boundary")

mutations = (
    helper_text.replace("const U8_MAX: i64 = 255", "const U8_MAX: i64 = 254", 1),
    helper_text.replace('"u8" -> value < U8_MIN or value > U8_MAX', '"u8" -> value < U8_MIN or value >= U8_MAX', 1),
    helper_text.replace('"i32" -> value < I32_MIN or value > I32_MAX', '"f32" -> value < I32_MIN or value > I32_MAX', 1),
    helper_text.replace("_ -> false", "_ -> true", 1),
)
for mutated in mutations:
    try:
        validate_helper(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("integer range source mutation escaped endpoint/set checking")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("literal comparison range proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CONSUMER])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    HERE / "literal_comparison_source.py",
    HELPER, CONSUMER, AST_NODES, AST_SIDE_TABLES, EFFECT_TYPE_SHAPE,
    POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == run(POSITIVE)[1], "literal comparison range report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "named signed and unsigned integer endpoints used by literal comparison diagnostics",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
