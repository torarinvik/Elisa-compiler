"""Admit proofs for the source-linked global-authority postfix cast-name classifier."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "global_authority_postfix_cast_name.elisa"
NEGATIVE = HERE / "global_authority_postfix_cast_name_rejected.elisa"
HELPER = ROOT / "src/semantic/global_authority_postfix_cast_name.elisa"
CONSUMER = ROOT / "src/semantic/check_global_authority_types.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


if not __debug__:
    raise SystemExit("run without Python -O")

CAST_NAMES = (
    "void", "bool", "char", "int", "i8", "i16", "i32", "i64", "isize",
    "s8", "s16", "s32", "s64", "u8", "u16", "u32", "u64", "usize",
    "uintptr", "f32", "f64", "sview", "cstr",
)
EXPECTED_POSITIVE = {
    "source_classifier_has_exact_lexical_rule",
    "every_builtin_postfix_cast_name_is_accepted",
    "uppercase_named_types_remain_cast_names",
    "empty_and_lowercase_unknown_names_are_not_casts",
}
EXPECTED_NEGATIVE = {
    "lowercase_dstr_is_a_postfix_cast",
    "unsupported_u128_is_a_postfix_cast",
    "empty_name_is_a_postfix_cast",
}


def compact(text: str) -> str:
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate source function {name}")
    return match.group(1)


source = HELPER.read_text()
source_uppercase_arm = "_ -> sview_len(name) > 0 and sview_at(name, 0) >= GA_ASCII_UPPER_A and sview_at(name, 0) <= GA_ASCII_UPPER_Z"
if "constGA_ASCII_UPPER_A:u8=65" not in compact(source):
    raise SystemExit("uppercase ASCII lower bound lost its named constant")
if "constGA_ASCII_UPPER_Z:u8=90" not in compact(source):
    raise SystemExit("uppercase ASCII upper bound lost its named constant")

def match_arms(block: str, fallback: str, description: str) -> None:
    arms = [line.strip() for line in block.splitlines() if line.strip()]
    if len(arms) != 2 or arms[-1] != fallback:
        raise SystemExit(f"{description} lost its exact literal and fallback arms")
    if not re.fullmatch(r'"[^"\\]+"(?:\s*\|\s*"[^"\\]+")*\s*->\s*true', arms[0]):
        raise SystemExit(f"{description} contains a non-literal or non-true arm")
    if re.findall(r'"([^"\\]+)"', arms[0]) != list(CAST_NAMES):
        raise SystemExit(f"{description} arms differ from the closed builtin set")


def contract_match(text: str, description: str) -> str:
    match = re.search(
        r"ensure\s+result\s*==\s*\(\s*when\s+name:\s*\n(.*?)^\s*\)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise SystemExit(f"{description} must state the closed set with pattern matching")
    return match.group(1)


source_contract = contract_match(function_body(source, "is_postfix_cast_name"), "production cast-name contract")
match_arms(source_contract, source_uppercase_arm, "production cast-name contract")
body_match = re.search(r"return\s+when\s+name:\s*\n(.*)", function_body(source, "is_postfix_cast_name"), re.DOTALL)
if not body_match:
    raise SystemExit("production cast-name classifier lost its exhaustive pattern match")
match_arms(body_match.group(1), "_ -> sview_len(name) > 0 and sview_at(name, 0) >= GA_ASCII_UPPER_A and sview_at(name, 0) <= GA_ASCII_UPPER_Z", "production cast-name implementation")

consumer = compact(CONSUMER.read_text())
if 'include"./global_authority_postfix_cast_name.elisa"' not in consumer:
    raise SystemExit("global-authority consumer no longer imports the proved classifier")
if "returnGlobalAuthorityPostfixCastName::is_postfix_cast_name(name)" not in compact(function_body(CONSUMER.read_text(), "ga_postfix_cast_name")):
    raise SystemExit("global-authority cast recognition no longer delegates to the proved classifier")
if "notga_postfix_cast_name(target)" not in consumer:
    raise SystemExit("postfix conversion admission no longer consumes the proved classifier")

proof_compact = compact(POSITIVE.read_text())
proof_uppercase_arm = "_ -> sview_len(name) > 0 and sview_at(name, 0) >= GlobalAuthorityPostfixCastName::GA_ASCII_UPPER_A and sview_at(name, 0) <= GlobalAuthorityPostfixCastName::GA_ASCII_UPPER_Z"
proof_contract = contract_match(POSITIVE.read_text(), "positive cast-name proof contract")
match_arms(proof_contract, proof_uppercase_arm, "positive cast-name proof contract")
for name in CAST_NAMES:
    if f'GlobalAuthorityPostfixCastName::is_postfix_cast_name("{name}")' not in proof_compact:
        raise SystemExit(f"positive proof no longer checks builtin postfix name {name!r}")

for path, expected in ((POSITIVE, EXPECTED_POSITIVE), (NEGATIVE, EXPECTED_NEGATIVE)):
    declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if declarations != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("global-authority postfix cast proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_include_closure([POSITIVE, NEGATIVE]), HELPER, CONSUMER,
]
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
assert positive == run(POSITIVE)[1], "postfix cast proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert EXPECTED_POSITIVE <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == EXPECTED_NEGATIVE
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed builtin postfix cast names plus the ASCII-uppercase type-name rule",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(EXPECTED_NEGATIVE),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
