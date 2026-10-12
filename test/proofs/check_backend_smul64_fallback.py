"""Admit the 32-bit target signed-i64 multiply fallback safety proofs."""
from __future__ import annotations

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
SOURCE = ROOT / "src/backend/codegen_binary_ops.elisa"
POSITIVE = HERE / "backend_smul64_fallback.elisa"
NEGATIVE = HERE / "backend_smul64_fallback_rejected.elisa"

POSITIVE_SHAPES = {
    "signed64_mul_fallback_divisor_is_nonzero": (
        "ensure result != 0 "
        "return 1 if left == 0 else (1 if left == (0 - 1) and right == I64_MIN else left)"
    ),
    "signed64_mul_min_neg_one_corner_divisor": (
        "requires left == (0 - 1) and right == I64_MIN "
        "ensure result == 1 "
        "return 1 if left == 0 else (1 if left == (0 - 1) and right == I64_MIN else left)"
    ),
}
NEGATIVE_SHAPES = {
    "false_claim_unchecked_left_is_always_nonzero": (
        "ensure result == true divisor: i64 = left return divisor != 0"
    ),
    "false_claim_min_neg_one_corner_keeps_minus_one": (
        "requires left == (0 - 1) and right == I64_MIN "
        "ensure result == true divisor: i64 = left return divisor == 1"
    ),
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def code_only(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():])
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


source = compact(code_only(function_section(SOURCE.read_text(), "emit_checked_int_binary")))
dispatch = compact(code_only(function_section(SOURCE.read_text(), "emit_binary")))
checked_dispatch = (
    "ifnotoverflow_wrapandnotunsignedand(operator==TokenKind.Plusor"
    "operator==TokenKind.Minusoroperator==TokenKind.Star):"
    "returnemit_checked_int_binary(operator,left,right,operand_type,structs,m,ctx,builder)"
)
if checked_dispatch not in dispatch:
    raise SystemExit("default signed add/subtract/multiply must reach the checked arithmetic helper")

ordered_source_fragments = (
    "ifoperator==TokenKind.Starandsignedandoperand_type.bits==64andstructs.target.target_pointer_bits==32:",
    'product:LLVMValueRef=LLVMBuildMul(builder,left,right,"smul64.product")',
    'int_min:LLVMValueRef=LLVMConstInt(wide_type,9223372036854775808,0)',
    'a_is_zero:LLVMValueRef=LLVMBuildICmp(builder,32,left,zero,"smul64.a.zero")',
    'a_is_minus_one:LLVMValueRef=LLVMBuildICmp(builder,32,left,minus_one,"smul64.a.neg1")',
    'b_is_min:LLVMValueRef=LLVMBuildICmp(builder,32,right,int_min,"smul64.b.min")',
    'min_corner:LLVMValueRef=LLVMBuildAnd(builder,a_is_minus_one,b_is_min,"smul64.min.corner")',
    'divisor_unsafe:LLVMValueRef=LLVMBuildOr(builder,a_is_zero,min_corner,"smul64.div.unsafe")',
    'divisor:LLVMValueRef=LLVMBuildSelect(builder,divisor_unsafe,one,left,"smul64.divisor")',
    'quotient:LLVMValueRef=LLVMBuildSDiv(builder,product,divisor,"smul64.quotient")',
    'quotient_differs:LLVMValueRef=LLVMBuildICmp(builder,33,quotient,right,"smul64.q.differs")',
    'back_test:LLVMValueRef=LLVMBuildAnd(builder,LLVMBuildNot(builder,divisor_unsafe,"smul64.div.safe"),quotient_differs,"smul64.back.test")',
    'overflow64:LLVMValueRef=LLVMBuildOr(builder,min_corner,back_test,"smul64.overflow")',
)
positions = [source.find(fragment) for fragment in ordered_source_fragments]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("32-bit signed-i64 multiply fallback no longer selects and guards the safe back-test in order")
if source.count('LLVMBuildSDiv(builder,product,divisor,"smul64.quotient")') != 1:
    raise SystemExit("fallback must have exactly one sdiv and it must use the guarded divisor")

positive_names = set(POSITIVE_SHAPES)
negative_names = set(NEGATIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("signed-i64 multiply fallback proof inventory is incomplete or contains extras")

for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    proof_text = code_only(path.read_text())
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer proves the intended fallback safety claim")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("signed-i64 multiply fallback proofs require a strict proof build")

inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
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
assert positive["summary"]["declarations"] == len(positive_names) + 2
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 4
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names) + 2
assert negative["summary"]["proven"] == len(positive_names) * 2 + len(negative_names)
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "nonzero divisor selection and MIN * -1 sdiv-corner neutralization in the 32-bit signed-i64 multiply fallback",
    "positive_obligations": positive["summary"]["proven"],
    "unsafe_simplifications_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
