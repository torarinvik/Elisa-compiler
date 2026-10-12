"""Admit source-bound proofs of signed negative pattern-literal conversion."""
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
POSITIVE = HERE / "backend_negative_literal.elisa"
NEGATIVE = HERE / "backend_negative_literal_rejected.elisa"

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


scope_text = SCOPE.read_text()
ops_text = OPS.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

parse = compact(function_section(ops_text, "parse_int_literal"))
guard = "min_magnitude:u64=9223372036854775807.u64()+1.u64()"
reject = "falsereturnifaccumulated>min_magnitude"
minimum = "out_value<-0-9223372036854775807-1ifaccumulated==min_magnitude"
safe_negation = "out_value<-0-accumulated.i64()ifaccumulated<min_magnitude"
if (parse.count(guard) != 1 or parse.count(reject) != 1 or parse.count(minimum) != 1 or
        parse.count(safe_negation) != 1 or
        not (parse.index(guard) < parse.index(reject) < parse.index(minimum) < parse.index(safe_negation))):
    raise SystemExit("negative-pattern parser changed its magnitude guard or safe conversion order")

positive_names = {
    "nonnegative_magnitude_cannot_be_i64_min",
    "nonnegative_magnitude_is_negated_exactly",
    "negative_i64_maximum_is_above_the_minimum",
}
negative_names = {"nonnegative_magnitude_can_be_i64_min"}
declared_positive = set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text, re.MULTILINE))
declared_negative = set(re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text, re.MULTILINE))
if declared_positive != positive_names or declared_negative != negative_names:
    raise SystemExit("backend negative-literal proof declaration inventory changed")
expected_positive = {
    "nonnegative_magnitude_cannot_be_i64_min": "requires magnitude >= 0 ensure result == true return magnitude != (0 - 9223372036854775807 - 1)",
    "nonnegative_magnitude_is_negated_exactly": "requires magnitude >= 0 ensure result == (0 - magnitude) return 0 - magnitude",
    "negative_i64_maximum_is_above_the_minimum": "ensure result == true return (0 - 9223372036854775807) > (0 - 9223372036854775807 - 1)",
}
expected_negative = {
    "nonnegative_magnitude_can_be_i64_min": "requires magnitude >= 0 ensure result == true return magnitude == (0 - 9223372036854775807 - 1)",
}
for name, expected in expected_positive.items():
    if compact(expected) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer states the signed-magnitude conversion theorem")
for name, expected in expected_negative.items():
    if compact(expected) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges the i64 minimum exclusion")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("backend negative-literal proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", OPS, SCOPE,
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
assert positive == replay(POSITIVE)[1], "backend negative-literal proof report changed across identical runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {finding["name"] for finding in negative["findings"]} == negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert negative_names.isdisjoint({item["name"] for item in negative["declaration_details"] if item.get("verified")})

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product, "proof product or pinned source tree changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-bound i64 negative pattern-literal conversion and minimum boundary",
    "proofs": len(positive_names),
    "producer_proven": positive["summary"]["proven"],
    "independently_replayed": positive["replay"]["replayed"],
    "false_claim_rejected": "nonnegative_magnitude_can_be_i64_min",
    "sources_sha256": hashes_before,
}))
