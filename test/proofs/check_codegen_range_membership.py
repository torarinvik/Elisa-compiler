"""Bind range-membership proofs to the backend's typed comparison path."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/backend/codegen_range_membership_policy.elisa"
EMITTER = ROOT / "src/backend/codegen_expr_membership.elisa"
COMPARISONS = ROOT / "src/backend/codegen_binary_ops.elisa"
VALUE_TYPES = ROOT / "src/backend/codegen_value_type.elisa"
POSITIVE = HERE / "codegen_range_membership.elisa"
NEGATIVE = HERE / "codegen_range_membership_rejected.elisa"
COMPARISON_PROOF_GATE = HERE / "check_codegen_comparison_predicates.py"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


policy_text = POLICY.read_text()
emitter_text = EMITTER.read_text()
comparison_text = COMPARISONS.read_text()
value_type_text = VALUE_TYPES.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
comparison_gate_text = COMPARISON_PROOF_GATE.read_text()

expected_operator_classifier = '''
def is_range_operator(operator: TokenKind) -> bool:
    ensure result == (
        operator == TokenKind.Range or
        operator == TokenKind.RangeLt or
        operator == TokenKind.RangeLe
    )
    return match operator:
        TokenKind.Range | TokenKind.RangeLt | TokenKind.RangeLe: true
        _: false
'''
expected_upper_operator = '''
def upper_operator(operator: TokenKind) -> TokenKind:
    ensure result == (
        TokenKind.LtEq if operator == TokenKind.Range or operator == TokenKind.RangeLe else
        TokenKind.Lt if operator == TokenKind.RangeLt else
        TokenKind.Error
    )
    return match operator:
        TokenKind.Range | TokenKind.RangeLe: TokenKind.LtEq
        TokenKind.RangeLt: TokenKind.Lt
        _: TokenKind.Error
'''
if "moduleBackendRangeMembershipPolicy:" not in compact(policy_text):
    raise SystemExit("range-membership policy module is missing")
if compact(function_section(policy_text, "is_range_operator")) != compact(expected_operator_classifier):
    raise SystemExit("range operator classifier changed without updating its source-bound proof")
if compact(function_section(policy_text, "upper_operator")) != compact(expected_upper_operator):
    raise SystemExit("range upper-operator policy changed without updating its source-bound proof")
if emitter_text.count('include "./codegen_range_membership_policy.elisa"') != 1:
    raise SystemExit("membership emitter must include the proved range policy exactly once")

emitter = compact(function_section(emitter_text, "emit_expression_membership"))
ordered_fragments = (
    "BackendRangeMembershipPolicy::is_range_operator(range_op)",
    "is_numeric_type(in_operand_type)orin_operand_type.kind==TypeKind.Signedorin_operand_type.kind==TypeKind.Unsigned",
    "emit_expression(in_left,in_operand_type,local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    "emit_expression(range_lo,in_operand_type,local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    "emit_expression(range_hi,in_operand_type,local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    "upper_operator:TokenKind=BackendRangeMembershipPolicy::upper_operator(range_op)",
    "emit_binary(TokenKind.GtEq,in_left_value,in_lo_value,in_operand_type,structs,runtime.fast_math,runtime.overflow_wrap,m,ctx,builder)",
    "emit_binary(upper_operator,in_left_value,in_hi_value,in_operand_type,structs,runtime.fast_math,runtime.overflow_wrap,m,ctx,builder)",
    'LLVMBuildAnd(builder,lo_ok,hi_ok,"in.range")',
    "nullreturnifnotis_numeric_type(in_operand_type)",
    "BackendRangeMembershipPolicy::is_range_operator(in_range_operator)",
    "in_upper_operator:TokenKind=BackendRangeMembershipPolicy::upper_operator(in_range_operator)",
    "Expr.Binary(in_lower_test,TokenKind.And,in_upper_test,in_range_line)",
    "emit_expression(in_range_test,ValueType{kind:TypeKind.Bool,bits:1},local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    'in_result<-LLVMBuildOr(builder,in_result,in_range_value,"in.range.or")',
    "emit_expression(resolved_shorthand_member(in_element,structs),in_operand_type,local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    "emit_binary(TokenKind.EqEq,in_left_value,in_element_value,in_operand_type,structs,runtime.fast_math,runtime.overflow_wrap,m,ctx,builder)",
    'in_result<-LLVMBuildOr(builder,in_result,in_eq,"in.or")',
)
positions = [emitter.find(fragment) for fragment in ordered_fragments]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("range membership must evaluate operands once and route both comparisons through emit_binary")
if any(fragment in emitter for fragment in (
    "lo_pred:u32=39if signed_cmpelse35",
    "LLVMBuildICmp(builder,lo_pred",
    "LLVMBuildICmp(builder,hi_pred",
    "LLVMBuildICmp(builder,32,in_left_value,in_element_value",
    "in_range_operator==TokenKind.RangeLtorin_range_operator==TokenKind.RangeLe",
    "TokenKind.LtEqifin_range_operator==TokenKind.RangeLeelseTokenKind.Lt",
)):
    raise SystemExit("range or scalar membership bypasses its proved range or typed-comparison policies")

integer_classifier = compact(function_section(value_type_text, "is_integer_type"))
if integer_classifier != compact('''
def is_integer_type(value_type: ValueType) -> bool:
    return value_type.kind == TypeKind.Signed or value_type.kind == TypeKind.Unsigned
'''):
    raise SystemExit("membership's integer type gate changed without updating its source-bound coverage")
numeric_classifier = compact(function_section(value_type_text, "is_numeric_type"))
if numeric_classifier != compact('''
def is_numeric_type(value_type: ValueType) -> bool:
    return is_integer_type(value_type) or value_type.kind == TypeKind.Float
'''):
    raise SystemExit("membership's scalar type gate changed without updating its source-bound coverage")
binary_emitter = compact(function_section(comparison_text, "emit_binary"))
float_route = (
    "ifoperand_type.kind==TypeKind.Float:",
    "float_predicate:i32=float_predicate_of(operator)",
    'LLVMBuildFCmp(builder,float_predicate,left,right,"fcmp")',
)
integer_route = (
    "predicate:i32=int_predicate_of(operator)",
    "resolved:i32=unsigned_predicate_of(predicate)ifunsignedelsepredicate",
    'LLVMBuildICmp(builder,resolved,left,right,"cmp")',
)
for route in (float_route, integer_route):
    route_positions = [binary_emitter.find(fragment) for fragment in route]
    if any(position < 0 for position in route_positions) or route_positions != sorted(route_positions):
        raise SystemExit("emit_binary no longer routes range operators through typed comparison predicates")
if not COMPARISON_PROOF_GATE.exists() or '"EqEq": 32' not in comparison_gate_text or \
        '"EqEq": 1' not in comparison_gate_text or \
        "float_predicate_of" not in comparison_gate_text or "unsigned_predicate_of" not in comparison_gate_text:
    raise SystemExit("typed comparison routing must remain covered by the comparison-predicate proof gate")

if 'include "../../src/parser/parser_tokens.elisa"' not in positive_text or \
        'include "../../src/backend/codegen_range_membership_policy.elisa"' not in positive_text or \
        'include "./codegen_range_membership.elisa"' not in negative_text:
    raise SystemExit("range membership proof fixtures must import the source policy")
positive_names = {
    "supported_range_operator_classifier_is_exact",
    "upper_comparison_classifier_is_exact",
    "all_three_range_forms_have_their_intended_upper_operator",
    "greater_than_range_operator_is_not_modeled_for_membership",
}
negative_names = {
    "false_claim_exclusive_range_uses_inclusive_upper_operator",
    "false_claim_greater_than_range_is_supported",
    "false_claim_inclusive_range_uses_strict_upper_operator",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("range-membership proof inventory changed")
required_claims = {
    "supported_range_operator_classifier_is_exact": "BackendRangeMembershipPolicy::is_range_operator(operator)==(operator==TokenKind.Rangeoroperator==TokenKind.RangeLtoroperator==TokenKind.RangeLe)",
    "upper_comparison_classifier_is_exact": "BackendRangeMembershipPolicy::upper_operator(operator)==expected",
    "all_three_range_forms_have_their_intended_upper_operator": "BackendRangeMembershipPolicy::is_range_operator(TokenKind.Range)andBackendRangeMembershipPolicy::upper_operator(TokenKind.Range)==TokenKind.LtEqandBackendRangeMembershipPolicy::is_range_operator(TokenKind.RangeLe)andBackendRangeMembershipPolicy::upper_operator(TokenKind.RangeLe)==TokenKind.LtEqandBackendRangeMembershipPolicy::is_range_operator(TokenKind.RangeLt)andBackendRangeMembershipPolicy::upper_operator(TokenKind.RangeLt)==TokenKind.Lt",
    "greater_than_range_operator_is_not_modeled_for_membership": "notBackendRangeMembershipPolicy::is_range_operator(TokenKind.RangeGt)andBackendRangeMembershipPolicy::upper_operator(TokenKind.RangeGt)==TokenKind.Error",
}
for name, claim in required_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive proof {name} no longer establishes its source-bound claim")
upper_classifier = compact(function_section(positive_text, "upper_comparison_classifier_is_exact"))
if "expected:TokenKind=matchoperator:TokenKind.Range|TokenKind.RangeLe:TokenKind.LtEqTokenKind.RangeLt:TokenKind.Lt_:TokenKind.Error" not in upper_classifier:
    raise SystemExit("upper-comparison proof no longer states the independent range-token specification")
expected_negative_claims = {
    "false_claim_exclusive_range_uses_inclusive_upper_operator": "BackendRangeMembershipPolicy::upper_operator(TokenKind.RangeLt)==TokenKind.LtEq",
    "false_claim_greater_than_range_is_supported": "BackendRangeMembershipPolicy::is_range_operator(TokenKind.RangeGt)",
    "false_claim_inclusive_range_uses_strict_upper_operator": "BackendRangeMembershipPolicy::upper_operator(TokenKind.RangeLe)==TokenKind.Lt",
}
for name, claim in expected_negative_claims.items():
    section = compact(function_section(negative_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"false-claim control {name} no longer asserts the expected rejected claim")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names),
                      "float_comparisons": "fcmp via emit_binary for ranges and scalar candidates"}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("range-membership proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POLICY, EMITTER,
    COMPARISONS, VALUE_TYPES, COMPARISON_PROOF_GATE, POSITIVE, NEGATIVE,
    *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "range-membership proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "range-membership proof inputs changed during admission"
