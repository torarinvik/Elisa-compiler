"""Admit source-bound proofs for backend decimal pattern accumulation."""
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
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
OPS = ROOT / "src/backend/codegen_binary_ops.elisa"
SCOPE = ROOT / "src/backend/codegen_scope.elisa"
FACADE = ROOT / "src/backend/codegen.elisa"
MODEL = HERE / "backend_decimal_accumulator_model.elisa"
POSITIVE = HERE / "backend_decimal_accumulator.elisa"
NEGATIVE = HERE / "backend_decimal_accumulator_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


ops_text = OPS.read_text()
scope_text = SCOPE.read_text()
facade_text = FACADE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

model_text = MODEL.read_text()
if 'include "./codegen_binary_ops.elisa"' not in scope_text:
    raise SystemExit("backend scope no longer includes scalar binary-operator lowering")
if 'include "./codegen_scope.elisa"' not in facade_text:
    raise SystemExit("backend facade no longer includes its scope assembly")
if compact("const U64_MAX: u64 = 18446744073709551615.u64()") not in compact(model_text):
    raise SystemExit("decimal accumulator u64 maximum changed")
if compact("const MAX_PREFIX_BEFORE_DECIMAL_DIGIT: u64 = 1844674407370955161.u64()") not in compact(model_text):
    raise SystemExit("decimal accumulator threshold changed")
guard_body = compact(function_section(model_text, "decimal_step_allowed"))
guard_contract = "ensure result == (digit <= 9.u64() and (accumulated < MAX_PREFIX_BEFORE_DECIMAL_DIGIT or (accumulated == MAX_PREFIX_BEFORE_DECIMAL_DIGIT and digit <= 5.u64())))"
guard_branches = (
    "false return if digit > 9.u64()",
    "true return if accumulated < MAX_PREFIX_BEFORE_DECIMAL_DIGIT",
    "return digit <= 5.u64() if accumulated == MAX_PREFIX_BEFORE_DECIMAL_DIGIT",
    "false",
)
if compact(guard_contract) not in guard_body or any(compact(branch) not in guard_body for branch in guard_branches):
    raise SystemExit("decimal accumulator guard changed")
value_body = compact(function_section(model_text, "decimal_step_value"))
if (compact("requires decimal_step_allowed(accumulated, digit)") not in value_body or
        compact("ensure result <= U64_MAX") not in value_body or
        compact("return accumulated * 10.u64() + digit") not in value_body):
    raise SystemExit("decimal accumulator value helper changed")

parse = compact(function_section(ops_text, "parse_int_literal"))
guard = "ifaccumulated>1844674407370955161.u64()or(accumulated==1844674407370955161.u64()anddigit>5.u64()):ok<-false"
step = "accumulated<-accumulated*10.u64()+digit"
if parse.count(guard) != 1 or parse.count(step) != 1:
    raise SystemExit("backend integer-pattern parser changed its checked decimal accumulation")
if parse.index(guard) >= parse.index(step):
    raise SystemExit("backend integer-pattern parser no longer checks the u64 boundary before multiply-add")
if "BackendDecimalLiteral::" in parse:
    raise SystemExit("backend integer-pattern parser must retain the inlined checked accumulator")
if "elifbyte<48orbyte>57:ok<-falseelse:digit:u64=(byte.i64()-48).u64()" not in parse:
    raise SystemExit("backend decimal path no longer constrains digits to 0..9 before the proved overflow guard")
for path, source in ((POSITIVE, positive_text), (NEGATIVE, negative_text)):
    if 'include "./backend_decimal_accumulator_model.elisa"' not in source:
        raise SystemExit(f"{path.name} no longer includes the arithmetic model")

positive_names = {
    "every_admitted_decimal_step_fits_u64",
    "inline_overflow_test_matches_the_decimal_model",
    "final_allowed_digit_reaches_u64_max",
    "every_lower_prefix_accepts_a_decimal_nine",
    "nondecimal_digit_is_rejected",
    "prefix_above_the_limit_is_rejected",
    "max_prefix_plus_six_is_rejected",
    "overflow_after_valid_separator_is_rejected",
    "one_below_max_prefix_with_nine_stays_below_u64_max",
}
negative_names = {"max_prefix_plus_six_is_admitted"}
declared_positive = set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text, re.MULTILINE))
declared_negative = set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text, re.MULTILINE))
if declared_positive != positive_names or declared_negative != negative_names:
    raise SystemExit("backend decimal accumulator proof declaration inventory changed")

expected_positive = {
    "every_admitted_decimal_step_fits_u64": "requires BackendDecimalLiteral::decimal_step_allowed(accumulated, digit) ensure result == true return BackendDecimalLiteral::decimal_step_value(accumulated, digit) <= BackendDecimalLiteral::U64_MAX",
    "inline_overflow_test_matches_the_decimal_model": "requires digit <= 9.u64() ensure result == true return (not (accumulated > BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT or (accumulated == BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT and digit > 5.u64()))) == BackendDecimalLiteral::decimal_step_allowed(accumulated, digit)",
    "final_allowed_digit_reaches_u64_max": "ensure result == true return BackendDecimalLiteral::decimal_step_allowed(BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT, 5.u64()) and BackendDecimalLiteral::decimal_step_value(BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT, 5.u64()) == BackendDecimalLiteral::U64_MAX",
    "every_lower_prefix_accepts_a_decimal_nine": "requires accumulated < BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT ensure result == true return BackendDecimalLiteral::decimal_step_allowed(accumulated, 9.u64())",
    "nondecimal_digit_is_rejected": "ensure result == true return not BackendDecimalLiteral::decimal_step_allowed(accumulated, 10.u64())",
    "prefix_above_the_limit_is_rejected": "requires accumulated > BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT ensure result == true return not BackendDecimalLiteral::decimal_step_allowed(accumulated, 0.u64())",
    "max_prefix_plus_six_is_rejected": "ensure result == true return not BackendDecimalLiteral::decimal_step_allowed(BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT, 6.u64())",
    "overflow_after_valid_separator_is_rejected": "ensure result == true prefix_after_separator: u64 = BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT return prefix_after_separator == BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT and not BackendDecimalLiteral::decimal_step_allowed(prefix_after_separator, 6.u64())",
    "one_below_max_prefix_with_nine_stays_below_u64_max": "ensure result == true return BackendDecimalLiteral::decimal_step_allowed(BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT - 1.u64(), 9.u64()) and BackendDecimalLiteral::decimal_step_value(BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT - 1.u64(), 9.u64()) == BackendDecimalLiteral::U64_MAX - 6.u64()",
}
expected_negative = {
    "max_prefix_plus_six_is_admitted": "ensure result == true return BackendDecimalLiteral::decimal_step_allowed(BackendDecimalLiteral::MAX_PREFIX_BEFORE_DECIMAL_DIGIT, 6.u64())",
}
for name, expected in expected_positive.items():
    if compact(expected) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer states its admitted decimal-accumulator theorem")
for name, expected in expected_negative.items():
    if compact(expected) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges the rejected decimal boundary")

overflow_case = "1844674407370955161_6"
if (len(overflow_case) != 21 or overflow_case[19] != "_" or
        overflow_case[:19] != "1844674407370955161" or
        int(overflow_case.replace("_", "")) != int("18446744073709551615") + 1):
    raise SystemExit("overflow-with-separator proof case no longer exceeds u64.max by one")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("backend decimal accumulator proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", MODEL, OPS, SCOPE, FACADE,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert {item["name"] for item in positive["declaration_details"] if item.get("verified")} == positive_names
assert positive == replay(POSITIVE)[1], "backend decimal accumulator proof report changed across identical runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert negative_names.isdisjoint({item["name"] for item in negative["declaration_details"] if item.get("verified")})

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product or pinned source tree changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-bound u64 decimal-accumulator guard and boundary behavior",
    "proofs": len(positive_names),
    "producer_proven": positive["summary"]["proven"],
    "independently_replayed": positive["replay"]["replayed"],
    "false_claim_rejected": "max_prefix_plus_six_is_admitted",
    "sources_sha256": hashes_before,
}))
