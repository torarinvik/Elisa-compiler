"""Admit source-bound integer signedness selection proofs for LLVM lowering."""
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
TOKENS = ROOT / "src/lexer/tokens.elisa"
POSITIVE = HERE / "backend_integer_signedness.elisa"
NEGATIVE = HERE / "backend_integer_signedness_rejected.elisa"

TOKEN_NAMES = ("Slash", "Percent", "RShift", "LShift")
TOKEN_CONST = {name: f"TOKEN_{name.upper()}" for name in TOKEN_NAMES}
OP_CODES = {
    "OP_SDIV": 1,
    "OP_UDIV": 2,
    "OP_SREM": 3,
    "OP_UREM": 4,
    "OP_ASHR": 5,
    "OP_LSHR": 6,
    "OP_SHL": 7,
}
POSITIVE_SHAPES = {
    "signed_division_selects_sdiv": (
        "requires operator == TOKEN_SLASH and not unsigned ensure result == OP_SDIV "
        "return OP_UDIV if operator == TOKEN_SLASH and unsigned else (OP_SDIV if operator == TOKEN_SLASH else 0)"
    ),
    "unsigned_division_selects_udiv": (
        "requires operator == TOKEN_SLASH and unsigned ensure result == OP_UDIV "
        "return OP_UDIV if operator == TOKEN_SLASH and unsigned else (OP_SDIV if operator == TOKEN_SLASH else 0)"
    ),
    "signed_remainder_selects_srem": (
        "requires operator == TOKEN_PERCENT and not unsigned ensure result == OP_SREM "
        "return OP_UREM if operator == TOKEN_PERCENT and unsigned else (OP_SREM if operator == TOKEN_PERCENT else 0)"
    ),
    "unsigned_remainder_selects_urem": (
        "requires operator == TOKEN_PERCENT and unsigned ensure result == OP_UREM "
        "return OP_UREM if operator == TOKEN_PERCENT and unsigned else (OP_SREM if operator == TOKEN_PERCENT else 0)"
    ),
    "signed_right_shift_selects_ashr": (
        "requires operator == TOKEN_RSHIFT and not unsigned ensure result == OP_ASHR "
        "return OP_LSHR if operator == TOKEN_RSHIFT and unsigned else (OP_ASHR if operator == TOKEN_RSHIFT else 0)"
    ),
    "unsigned_right_shift_selects_lshr": (
        "requires operator == TOKEN_RSHIFT and unsigned ensure result == OP_LSHR "
        "return OP_LSHR if operator == TOKEN_RSHIFT and unsigned else (OP_ASHR if operator == TOKEN_RSHIFT else 0)"
    ),
    "left_shift_uses_shl_for_both_signednesses": (
        "requires operator == TOKEN_LSHIFT ensure result == OP_SHL "
        "return OP_SHL if operator == TOKEN_LSHIFT else 0"
    ),
}
NEGATIVE_SHAPES = {
    "false_claim_signed_division_selects_udiv": (
        "requires operator == TOKEN_SLASH and not unsigned ensure result == OP_UDIV "
        "return OP_UDIV if operator == TOKEN_SLASH and unsigned else (OP_SDIV if operator == TOKEN_SLASH else 0)"
    ),
    "false_claim_unsigned_remainder_selects_srem": (
        "requires operator == TOKEN_PERCENT and unsigned ensure result == OP_SREM "
        "return OP_UREM if operator == TOKEN_PERCENT and unsigned else (OP_SREM if operator == TOKEN_PERCENT else 0)"
    ),
    "false_claim_signed_right_shift_selects_lshr": (
        "requires operator == TOKEN_RSHIFT and not unsigned ensure result == OP_LSHR "
        "return OP_LSHR if operator == TOKEN_RSHIFT and unsigned else (OP_ASHR if operator == TOKEN_RSHIFT else 0)"
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


def token_ordinals() -> dict[str, int]:
    text = TOKENS.read_text()
    match = re.search(r"(?ms)^\s{8}const enum TokenKind of u8:\n(.*?)(?=^\s{8}struct Token:)", text)
    if match is None:
        raise SystemExit("could not locate the u8 TokenKind declaration")
    names = [line.strip() for line in match.group(1).splitlines()
             if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]
    return {name: index for index, name in enumerate(names)}


def function_constants(source: str, names: tuple[str, ...]) -> dict[str, int]:
    result = {}
    for name in names:
        match = re.search(rf"(?m)^const {re.escape(name)}: i64 = (\d+)$", source)
        if match is None:
            raise SystemExit(f"missing proof constant {name}")
        result[name] = int(match.group(1))
    return result


source_text = SOURCE.read_text()
dispatch = compact(code_only(function_section(source_text, "emit_binary")))
required_dispatch = (
    'LLVMBuildShl(builder,left,right,"shl")returnifoperator==TokenKind.LShift'
    'ifoperator==TokenKind.Slash:returnLLVMBuildUDiv(builder,left,right,"div")ifunsignedelseLLVMBuildSDiv(builder,left,right,"div")'
    'ifoperator==TokenKind.Percent:returnLLVMBuildURem(builder,left,right,"rem")ifunsignedelseLLVMBuildSRem(builder,left,right,"rem")'
    'ifoperator==TokenKind.RShift:returnLLVMBuildLShr(builder,left,right,"shr")ifunsignedelseLLVMBuildAShr(builder,left,right,"shr")'
)
if required_dispatch not in dispatch:
    raise SystemExit("integer division, remainder, or shift signedness dispatch changed")
if "unsigned:bool=operand_type.kind==TypeKind.Unsigned" not in dispatch:
    raise SystemExit("integer lowering no longer derives signedness from the operand type")

ordinals = token_ordinals()
positive_text = POSITIVE.read_text()
expected_tokens = {TOKEN_CONST[name]: ordinals[name] for name in TOKEN_NAMES}
actual_tokens = function_constants(positive_text, tuple(expected_tokens))
if actual_tokens != expected_tokens:
    raise SystemExit("proof TokenKind constants no longer match the production enum ordinals")
if function_constants(positive_text, tuple(OP_CODES)) != OP_CODES:
    raise SystemExit("proof opcode model constants changed")

positive_names = set(POSITIVE_SHAPES)
negative_names = set(NEGATIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != negative_names:
    raise SystemExit("integer signedness proof inventory is incomplete or contains extras")

for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    proof_text = code_only(path.read_text())
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer proves its intended signedness case")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("integer signedness proofs require a strict proof build")

inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    TOKENS,
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
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + len(OP_CODES) + len(TOKEN_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 14
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names) + len(OP_CODES) + len(TOKEN_NAMES)
assert negative["summary"]["obligations"] == 20 and negative["summary"]["proven"] == 17
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "signed and unsigned integer division, remainder, and right-shift selection, plus signedness-independent left shift",
    "positive_obligations": positive["summary"]["proven"],
    "wrong_signedness_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
