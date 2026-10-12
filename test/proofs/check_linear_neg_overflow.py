"""Admit the unary-negation overflow contract in Semantic's checked arithmetic."""
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
SOURCE = ROOT / "src/semantic/check_ensure_strict.elisa"
POSITIVE = HERE / "linear_neg_overflow.elisa"
NEGATIVE = HERE / "linear_neg_overflow_rejected.elisa"

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
    return source[start:end]


source_text = SOURCE.read_text()
maximum = compact(function_section(source_text, "linear_i64_max"))
minimum = compact(function_section(source_text, "linear_i64_min"))
if "return9223372036854775807" not in maximum:
    raise SystemExit("linear_i64_max no longer returns the signed 64-bit upper bound")
if "return0-9223372036854775807-1" not in minimum:
    raise SystemExit("linear_i64_min no longer returns the signed 64-bit lower bound")

negate = compact(function_section(source_text, "linear_neg_safe"))
if not negate.startswith("deflinear_neg_safe(operand:i64)->(known:bool,value:i64):returnlinear_sub_safe(0,operand)"):
    raise SystemExit("linear_neg_safe no longer delegates negation to checked subtraction from zero")

sub = compact(function_section(source_text, "linear_sub_safe"))
sub_guards = (
    "return(false,0)ifright>0andleft<linear_i64_min()+right",
    "return(false,0)ifright<0andleft>linear_i64_max()+right",
    "return(true,left-right)",
)
positions = [sub.find(fragment) for fragment in sub_guards]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("checked subtraction must reject both underflow and overflow before returning the difference")

positive_names = {"negate_nonminimum"}
negative_names = {"false_minimum_negation_is_safe"}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_shape = "requires operand != (0 - 9223372036854775807 - 1) ensure result == (0 - operand) return 0 - operand"
if compact(positive_shape) not in compact(function_section(POSITIVE.read_text(), "negate_nonminimum")):
    raise SystemExit("negate_nonminimum no longer states the checked helper's exact-result contract")
negative_shape = "requires operand == (0 - 9223372036854775807 - 1) ensure result == true return operand != (0 - 9223372036854775807 - 1)"
if compact(negative_shape) not in compact(function_section(NEGATIVE.read_text(), "false_minimum_negation_is_safe")):
    raise SystemExit("false_minimum_negation_is_safe no longer challenges the excluded i64 minimum")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("checked negation proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE,
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
assert positive["summary"]["declarations"] == 1
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 2
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "linear negation proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == 2
assert negative["summary"]["obligations"] == 4 and negative["summary"]["proven"] == 3
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert negative_names.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "checked i64 negation has its mathematical value whenever the operand is not i64 minimum",
    "positive_obligations": positive["summary"]["proven"],
    "false_minimum_claim_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
