"""Admit source-pinned proofs of conservative boolean-literal branch facts."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "ownership_literal_bool.elisa"
NEGATIVE = HERE / "ownership_literal_bool_rejected.elisa"
FLOW = ROOT / "src/semantic/ownership_control_flow.elisa"
DERIVED = ROOT / "src/semantic/check_derived_source_frontier.elisa"
SEMANTIC_ROOT = ROOT / "src/semantic/semantic.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

flow_source = FLOW.read_text()
depth_constant = "const OWNERSHIP_FLOW_ANALYSIS_DEPTH_LIMIT: usize = 128"
if depth_constant not in flow_source:
    raise SystemExit("ownership literal recognizer depth bound lost its named constant")
for literal, declaration in (
    ("128", depth_constant),
    ("64", "const OWNERSHIP_FLOW_LOOP_FIXED_POINT_LIMIT: usize = 64"),
    ("8192", "const OWNERSHIP_FLOW_INITIAL_FUEL: usize = 8192"),
):
    if declaration not in flow_source or len(re.findall(rf"(?<!\d){literal}(?!\d)", flow_source)) != 1:
        raise SystemExit(f"ownership analysis limit {literal} must be named once and reused")
def compact_source(text):
    # Keep spaces inside strings, but remove comments and layout for stable source anchors.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))


def source_function_raw(source, name):
    definition = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", source)
    if not definition:
        raise SystemExit(f"production consumer function is missing: {name}")
    tail = source[definition.end():]
    following = re.search(r"(?m)^\s*def\s+", tail)
    end = definition.end() + following.start() if following else len(source)
    return source[definition.start():end]


def source_function(source, name):
    return compact_source(source_function_raw(source, name))


def source_field_lines(source, name, field):
    body = source_function_raw(source, name)
    return [compact_source(line) for line in body.splitlines() if re.search(rf"\b(?:literal|literal_guard)\.{field}\b", line)]


def source_reachability_writes(source, name):
    body = source_function_raw(source, name)
    return [compact_source(line) for line in body.splitlines() if ".reachable<-" in compact_source(line)]


def source_control_transfer_lines(source, name):
    body = source_function_raw(source, name)
    lines = []
    for line in body.splitlines():
        without_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
        code = without_strings.split("#", 1)[0]
        if re.search(r"\b(return|break|continue)\b", code):
            lines.append(compact_source(line))
    return lines


def require_ordered(body, anchors, label):
    positions = [body.find(anchor) for anchor in anchors]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} changed or reordered a source-bound proof anchor")


def require_contiguous(body, fragments, label):
    expected = compact_source("\n".join(fragments))
    if expected not in body:
        raise SystemExit(f"{label} no longer preserves its exact branch transfer sequence")


def match_arm_signature(source, function_name, arm_header):
    """Return exact token lines with relative indentation for one match arm."""
    lines = source_function_raw(source, function_name).splitlines()
    for index, line in enumerate(lines):
        code = line.split("#", 1)[0].rstrip()
        if code.strip() != arm_header:
            continue
        base_indent = len(code) - len(code.lstrip(" "))
        signature = []
        for candidate in lines[index:]:
            code = candidate.split("#", 1)[0].rstrip()
            if not code.strip():
                continue
            indent = len(code) - len(code.lstrip(" "))
            if signature and indent <= base_indent:
                break
            signature.append((indent - base_indent, compact_source(code)))
        return tuple(signature)
    raise SystemExit(f"match arm is missing from {function_name}: {arm_header}")


def require_match_arm_structure(source, function_name, arm_header, expected, label):
    actual_signature = match_arm_signature(source, function_name, arm_header)
    expected_signature = match_arm_signature(
        "def fixture():\n" + "\n".join("    " + line for line in expected.splitlines()),
        "fixture",
        arm_header,
    )
    if actual_signature != expected_signature:
        raise SystemExit(f"{label} changed its branch body or nesting")


def nest_match_arm_under_guard(source, function_name, arm_header, guard):
    """Mutation fixture: wrap the complete arm body without changing its tokens."""
    function = source_function_raw(source, function_name)
    lines = function.splitlines()
    for index, line in enumerate(lines):
        code = line.split("#", 1)[0].rstrip()
        if code.strip() != arm_header:
            continue
        base_indent = len(code) - len(code.lstrip(" "))
        end = index + 1
        while end < len(lines):
            candidate = lines[end].split("#", 1)[0].rstrip()
            if candidate.strip() and len(candidate) - len(candidate.lstrip(" ")) <= base_indent:
                break
            end += 1
        rewritten = [lines[index], " " * (base_indent + 4) + guard]
        rewritten.extend("    " + row if row.strip() else row for row in lines[index + 1:end])
        return "\n".join(lines[:index] + rewritten + lines[end:])
    raise SystemExit(f"mutation fixture could not find {function_name}: {arm_header}")


start = flow_source.find("def ownership_literal_bool(")
if start < 0:
    raise SystemExit("production literal-boolean recognizer is missing")
end = flow_source.find("\n        def ", start + len("def ownership_literal_bool("))
function = flow_source[start:end if end >= 0 else None]
compact = compact_source(function)
expected_recognizer = (
    "def ownership_literal_bool(expression: Ast::Expr, depth: usize = 0) -> (known: bool, value: bool) can[Abort.Panic]: "
    "return (false, false) if depth >= OWNERSHIP_FLOW_ANALYSIS_DEPTH_LIMIT "
    "match expression: "
    "Expr.BoolLit(value, _): return (true, value) "
    "Expr.Paren(inner, _): return ownership_literal_bool(inner, depth + 1) "
    "_: return (false, false)"
)
if compact != compact_source(expected_recognizer):
    raise SystemExit("literal-boolean production recognizer changed from its exact depth-first definition")

proof_source = POSITIVE.read_text()
known_model = source_function(proof_source, "fact_is_known_at_node")
require_ordered(known_model, (
    "requiresnot(is_boolean_literalandis_parenthesized)",
    "ensureresult==(depth<OWNERSHIP_LITERAL_BOOL_PROOF_DEPTH_LIMITand(is_boolean_literalor(notis_boolean_literalandis_parenthesizedandinner_known)))",
    "falsereturnifdepth>=OWNERSHIP_LITERAL_BOOL_PROOF_DEPTH_LIMIT",
    "truereturnifis_boolean_literal",
    "returninner_knownifis_parenthesized",
    "returnfalse",
), "knownness model")
value_model = source_function(proof_source, "fact_value_at_node")
require_ordered(value_model, (
    "requiresnot(is_boolean_literalandis_parenthesized)",
    "requiresis_boolean_literalornotis_parenthesizedorinner_knownornotinner_value",
    "ensureresult==(depth<OWNERSHIP_LITERAL_BOOL_PROOF_DEPTH_LIMITand((is_boolean_literalandliteral_value)or(notis_boolean_literalandis_parenthesizedandinner_value)))",
    "falsereturnifdepth>=OWNERSHIP_LITERAL_BOOL_PROOF_DEPTH_LIMIT",
    "returnliteral_valueifis_boolean_literal",
    "returninner_valueifis_parenthesized",
    "returnfalse",
), "value model")

consumer_sites = {
    "ownership_flow_expression": (2, 4, 3, (
        "literal=ownership_literal_bool(left)",
        "ifliteral.known:ownership_flow_expression(right,owner,table,flow,work,depth+1)if(operator==TokenKind.Andandliteral.value)or(operator==TokenKind.Orandnotliteral.value)",
        "literal=ownership_literal_bool(condition)",
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    )),
    "ownership_flow_loop": (1, 2, 2, (
        "literal=ownership_literal_bool(condition)",
        "back.reachable<-back.reachableandliteral.valueifliteral.known",
        "elifliteral.knownandliteral.value:flow.reachable<-false",
    )),
    "ownership_flow_statements": (1, 2, 2, (
        "literal=ownership_literal_bool(condition)",
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    )),
}
for name, (expected_calls, expected_value_uses, expected_known_uses, anchors) in consumer_sites.items():
    body = source_function(flow_source, name)
    if body.count("ownership_literal_bool(") != expected_calls:
        raise SystemExit(f"{name} literal-boolean call-site count changed")
    if len(re.findall(r"(?:literal|literal_guard)\.value", body)) != expected_value_uses:
        raise SystemExit(f"{name} gained an unpinned literal value use")
    if len(re.findall(r"(?:literal|literal_guard)\.known", body)) != expected_known_uses:
        raise SystemExit(f"{name} gained an unpinned literal knownness use")
    require_ordered(body, anchors, name)

expected_known_lines = {
    "ownership_flow_expression": [
        "ifliteral.known:",
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    ],
    "ownership_flow_loop": [
        "back.reachable<-back.reachableandliteral.valueifliteral.known",
        "elifliteral.knownandliteral.value:",
    ],
    "ownership_flow_statements": [
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    ],
}
expected_reachability_writes = {
    "ownership_flow_expression": [
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
    ],
    "ownership_flow_loop": [
        "back.reachable<-back.reachableandliteral.valueifliteral.known",
        "flow.reachable<-false",
        "flow.reachable<-entry.reachable",
    ],
    "ownership_flow_statements": [
        "yes.reachable<-yes.reachableandliteral.valueifliteral.known",
        "no.reachable<-no.reachableandnotliteral.valueifliteral.known",
        "flow.reachable<-false",
    ],
}
for name in consumer_sites:
    if source_field_lines(flow_source, name, "known") != expected_known_lines[name]:
        raise SystemExit(f"{name} has an unpinned or changed literal-knownness use")
    if source_reachability_writes(flow_source, name) != expected_reachability_writes[name]:
        raise SystemExit(f"{name} has an unpinned reachability update")

expected_flow_control_transfers = {
    "ownership_flow_expression": [
        "returnifnotownership_flow_step(flow,work,depth)",
        "return",
        "return",
        "return",
    ],
    "ownership_flow_loop": ["return"],
    "ownership_flow_statements": ["returnifnotownership_flow_step(flow,work,depth)"],
}
for name, expected in expected_flow_control_transfers.items():
    if source_control_transfer_lines(flow_source, name) != expected:
        raise SystemExit(f"{name} gained or reordered a control transfer around ownership analysis")

require_contiguous(source_function(flow_source, "ownership_flow_expression"), (
    "literal = ownership_literal_bool(condition)",
    "yes.reachable <- yes.reachable and literal.value if literal.known",
    "no.reachable <- no.reachable and not literal.value if literal.known",
    "ownership_flow_expression(then_value, owner, table, &yes, work, depth + 1)",
    "ownership_flow_expression(else_value, owner, table, &no, work, depth + 1)",
    "ownership_flow_join(flow, &yes, &no)",
), "expression if ownership branches")
require_contiguous(source_function(flow_source, "ownership_flow_statements"), (
    "literal = ownership_literal_bool(condition)",
    "yes.reachable <- yes.reachable and literal.value if literal.known",
    "no.reachable <- no.reachable and not literal.value if literal.known",
    "ownership_flow_statements(&then_body, owner, table, &yes, work, depth + 1)",
    "ownership_flow_statements(&else_body, owner, table, &no, work, depth + 1)",
    "ownership_flow_join(flow, &yes, &no)",
), "statement if ownership branches")

# Every dataflow use is individually tied to its conservative knownness guard.
derived_source = DERIVED.read_text()
derived_sites = {
    "derived_source_effects": (1, 2, 2, (
        "literal=ownership_literal_bool(condition)",
        "left.reachable<-falseifliteral.knownandnotliteral.value",
        "right.reachable<-falseifliteral.knownandliteral.value",
        "derived_source_effects(yes,owner,table,&left,depth+1)ifleft.reachable",
        "derived_source_effects(no,owner,table,&right,depth+1)ifright.reachable",
    )),
    "derived_source_loop": (1, 2, 2, (
        "literal=ownership_literal_bool(condition)",
        "ifliteral.knownandnotliteral.value",
        "derived_source_effects(condition,owner,table,flow)return",
        "elifliteral.knownandliteral.value:flow.reachable<-false",
    )),
    "derived_source_walk": (2, 3, 3, (
        "literal=ownership_literal_bool(condition)",
        "left.reachable<-falseifliteral.knownandnotliteral.value",
        "right.reachable<-falseifliteral.knownandliteral.value",
        "literal_guard=ownership_literal_bool(arm.guard)",
        "branch.reachable<-falseifliteral_guard.knownandnotliteral_guard.value",
    )),
}
for name, (expected_calls, expected_value_uses, expected_known_uses, anchors) in derived_sites.items():
    body = source_function(derived_source, name)
    if body.count("ownership_literal_bool(") != expected_calls:
        raise SystemExit(f"{name} literal-boolean call-site count changed")
    if len(re.findall(r"(?:literal|literal_guard)\.value", body)) != expected_value_uses:
        raise SystemExit(f"{name} gained an unpinned literal value use")
    if len(re.findall(r"(?:literal|literal_guard)\.known", body)) != expected_known_uses:
        raise SystemExit(f"{name} gained an unpinned literal knownness use")
    require_ordered(body, anchors, name)

expected_derived_known_lines = {
    "derived_source_effects": [
        "left.reachable<-falseifliteral.knownandnotliteral.value",
        "right.reachable<-falseifliteral.knownandliteral.value",
    ],
    "derived_source_loop": [
        "ifliteral.knownandnotliteral.value:",
        "elifliteral.knownandliteral.value:",
    ],
    "derived_source_walk": [
        "left.reachable<-falseifliteral.knownandnotliteral.value",
        "right.reachable<-falseifliteral.knownandliteral.value",
        "branch.reachable<-falseifliteral_guard.knownandnotliteral_guard.value",
    ],
}
expected_derived_reachability_writes = {
    "derived_source_effects": [
        "left.reachable<-falseifliteral.knownandnotliteral.value",
        "right.reachable<-falseifliteral.knownandliteral.value",
    ],
    "derived_source_loop": [
        "flow.reachable<-entry.reachable",
        "flow.reachable<-false",
        "flow.reachable<-entry.reachable",
    ],
    "derived_source_walk": [
        "flow.reachable<-false",
        "left.reachable<-falseifliteral.knownandnotliteral.value",
        "right.reachable<-falseifliteral.knownandliteral.value",
        "joined.reachable<-false",
        "branch.reachable<-falseifliteral_guard.knownandnotliteral_guard.value",
        "flow.reachable<-false",
    ],
}
for name in derived_sites:
    if source_field_lines(derived_source, name, "known") != expected_derived_known_lines[name]:
        raise SystemExit(f"{name} has an unpinned or changed literal-knownness use")
    if source_reachability_writes(derived_source, name) != expected_derived_reachability_writes[name]:
        raise SystemExit(f"{name} has an unpinned reachability update")

expected_derived_control_transfers = {
    "derived_source_effects": ["return"],
    "derived_source_loop": [
        "return",
        "return",
        "breakiffuel==0ornothead.coverage_complete",
    ],
    "derived_source_walk": [
        "return",
        "returnifnotflow.reachable",
        "return",
        "continueifnotresolvedornotownership_binding_ids_equal(declared.binding_id,id)ornotdeclared.state_identity.knownordeclared.state_identity.protocol",
    ],
}
for name, expected in expected_derived_control_transfers.items():
    if source_control_transfer_lines(derived_source, name) != expected:
        raise SystemExit(f"{name} gained or reordered a control transfer around derived-state analysis")

require_contiguous(source_function(derived_source, "derived_source_effects"), (
    "literal = ownership_literal_bool(condition)",
    "left.reachable <- false if literal.known and not literal.value",
    "right.reachable <- false if literal.known and literal.value",
    "derived_source_effects(yes, owner, table, &left, depth + 1) if left.reachable",
    "derived_source_effects(no, owner, table, &right, depth + 1) if right.reachable",
    "derived_source_join(flow, &left, &right)",
), "expression if derived-state branches")
require_contiguous(source_function(derived_source, "derived_source_walk"), (
    "literal = ownership_literal_bool(condition)",
    "left.reachable <- false if literal.known and not literal.value",
    "right.reachable <- false if literal.known and literal.value",
    "table <- derived_source_walk(&yes, expected, scope, owner, rules, &left, fuel, table, depth + 1, report)",
    "table <- derived_source_walk(&no, expected, scope, owner, rules, &right, fuel, table, depth + 1, report)",
    "derived_source_join(flow, &left, &right)",
), "statement if derived-state branches")

# The compact-source checks above prove token presence and order. These
# indentation-preserving signatures also prove that every literal-knownness
# consumer remains in the intended match arm, rather than behind a new guard.
literal_if_arms = (
    (flow_source, "ownership_flow_expression", "Expr.If(condition, then_value, else_value, _):", "ownership expression if", """Expr.If(condition, then_value, else_value, _):
    ownership_flow_expression(condition, owner, table, flow, work, depth + 1)
    yes: mutable OwnershipFrontier = ownership_flow_clone(flow)
    no: mutable OwnershipFrontier = ownership_flow_clone(flow)
    literal = ownership_literal_bool(condition)
    yes.reachable <- yes.reachable and literal.value if literal.known
    no.reachable <- no.reachable and not literal.value if literal.known
    ownership_flow_expression(then_value, owner, table, &yes, work, depth + 1)
    ownership_flow_expression(else_value, owner, table, &no, work, depth + 1)
    ownership_flow_join(flow, &yes, &no)"""),
    (flow_source, "ownership_flow_statements", "Stmt.If(condition, then_body, else_body, _):", "ownership statement if", """Stmt.If(condition, then_body, else_body, _):
    ownership_flow_expression(condition, owner, table, flow, work, depth + 1)
    yes: mutable OwnershipFrontier = ownership_flow_clone(flow)
    no: mutable OwnershipFrontier = ownership_flow_clone(flow)
    literal = ownership_literal_bool(condition)
    yes.reachable <- yes.reachable and literal.value if literal.known
    no.reachable <- no.reachable and not literal.value if literal.known
    ownership_flow_statements(&then_body, owner, table, &yes, work, depth + 1)
    ownership_flow_statements(&else_body, owner, table, &no, work, depth + 1)
    ownership_flow_join(flow, &yes, &no)"""),
    (derived_source, "derived_source_effects", "Expr.If(condition, yes, no, _):", "derived-source expression if", """Expr.If(condition, yes, no, _):
    derived_source_effects(condition, owner, table, flow, depth + 1)
    left: mutable DerivedSourceFrontier = derived_source_clone(flow)
    right: mutable DerivedSourceFrontier = derived_source_clone(flow)
    literal = ownership_literal_bool(condition)
    left.reachable <- false if literal.known and not literal.value
    right.reachable <- false if literal.known and literal.value
    derived_source_effects(yes, owner, table, &left, depth + 1) if left.reachable
    derived_source_effects(no, owner, table, &right, depth + 1) if right.reachable
    derived_source_join(flow, &left, &right)"""),
    (derived_source, "derived_source_walk", "Stmt.If(condition, yes, no, _):", "derived-source statement if", """Stmt.If(condition, yes, no, _):
    derived_source_effects(condition, owner, table, flow)
    left: mutable DerivedSourceFrontier = derived_source_clone(flow)
    right: mutable DerivedSourceFrontier = derived_source_clone(flow)
    literal = ownership_literal_bool(condition)
    left.reachable <- false if literal.known and not literal.value
    right.reachable <- false if literal.known and literal.value
    table <- derived_source_walk(&yes, expected, scope, owner, rules, &left, fuel, table, depth + 1, report)
    table <- derived_source_walk(&no, expected, scope, owner, rules, &right, fuel, table, depth + 1, report)
    derived_source_join(flow, &left, &right)"""),
)
for source, function_name, arm_header, label, expected in literal_if_arms:
    require_match_arm_structure(source, function_name, arm_header, expected, label)

# This reproduces the bypass discovered in the coverage audit. Compact token
# counts remain unchanged by the wrapper; the structural gate above must refuse
# the variant because the direct-literal branches would skip ownership flow.
mutated_expression_if = nest_match_arm_under_guard(
    flow_source,
    "ownership_flow_expression",
    "Expr.If(condition, then_value, else_value, _):",
    "if not (condition is Expr.BoolLit(_, _)):",
)
mutated_expression_body = source_function(mutated_expression_if, "ownership_flow_expression")
if mutated_expression_body.count("ownership_literal_bool(") != consumer_sites["ownership_flow_expression"][0] or \
        len(re.findall(r"(?:literal|literal_guard)\.value", mutated_expression_body)) != consumer_sites["ownership_flow_expression"][1] or \
        len(re.findall(r"(?:literal|literal_guard)\.known", mutated_expression_body)) != consumer_sites["ownership_flow_expression"][2]:
    raise SystemExit("nested-guard mutation no longer preserves the legacy call-site and field-use counts")
if source_field_lines(mutated_expression_if, "ownership_flow_expression", "known") != expected_known_lines["ownership_flow_expression"] or \
        source_reachability_writes(mutated_expression_if, "ownership_flow_expression") != expected_reachability_writes["ownership_flow_expression"] or \
        source_control_transfer_lines(mutated_expression_if, "ownership_flow_expression") != expected_flow_control_transfers["ownership_flow_expression"]:
    raise SystemExit("nested-guard mutation no longer preserves the legacy field, write, and transfer inventories")
require_ordered(mutated_expression_body, consumer_sites["ownership_flow_expression"][3], "mutated ownership expression if")
require_contiguous(mutated_expression_body, (
    "literal = ownership_literal_bool(condition)",
    "yes.reachable <- yes.reachable and literal.value if literal.known",
    "no.reachable <- no.reachable and not literal.value if literal.known",
    "ownership_flow_expression(then_value, owner, table, &yes, work, depth + 1)",
    "ownership_flow_expression(else_value, owner, table, &no, work, depth + 1)",
    "ownership_flow_join(flow, &yes, &no)",
), "mutated ownership expression if")
try:
    require_match_arm_structure(
        mutated_expression_if,
        "ownership_flow_expression",
        "Expr.If(condition, then_value, else_value, _):",
        literal_if_arms[0][4],
        "mutated ownership expression if",
    )
except SystemExit:
    pass
else:
    raise SystemExit("ownership literal-bool source gate accepted the nested-guard bypass mutation")

semantic_root = SEMANTIC_ROOT.read_text()
for include in ('include "./ownership_control_flow.elisa"',
                'include "./check_derived_source_frontier.elisa"'):
    if include not in semantic_root:
        raise SystemExit(f"semantic root no longer includes the literal-boolean consumer: {include}")

proof_source = POSITIVE.read_text()
if "const OWNERSHIP_LITERAL_BOOL_PROOF_DEPTH_LIMIT: usize = 128" not in proof_source:
    raise SystemExit("proof model depth bound does not match the production constant")
positive_names = {
    "boolean_literals_are_known_and_keep_their_value",
    "parentheses_preserve_the_inner_fact",
    "parenthesis_at_the_depth_boundary_is_unknown_and_false",
    "unknown_facts_never_carry_a_true_value",
    "the_depth_cutoff_discards_literal_facts",
    "an_unsupported_expression_is_conservatively_unknown",
    "a_parenthesized_unknown_stays_unknown_and_false",
}
negative_names = {
    "depth_limited_boolean_may_remain_known",
    "unsupported_expression_may_supply_a_truth_value",
    "parentheses_may_invent_knownness",
    "parenthesized_unknown_may_be_true",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    found = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", path.read_text()))
    if not expected <= found:
        raise SystemExit(f"{path.name} lost a branch law: {sorted(expected - found)}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("ownership literal-boolean proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE]), FLOW, DERIVED, SEMANTIC_ROOT]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "literal-boolean proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "boolean literal and parenthesis propagation at one ownership-analysis step",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": sorted(negative_names),
                  "sources_sha256": hashes_before}, sort_keys=True))
