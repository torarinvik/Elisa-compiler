"""Admit the signed addition/subtraction overflow guards in Semantic's constant arithmetic."""
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
INDEX_FOLD = ROOT / "src/semantic/check_index_out_of_bounds.elisa"
POSITIVE = HERE / "linear_add_sub_overflow.elisa"
NEGATIVE = HERE / "linear_add_sub_overflow_rejected.elisa"

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

add_fn = compact(function_section(source_text, "linear_add_safe"))
add_order = (
    "return(false,0)ifright>0andleft>linear_i64_max()-right",
    "return(false,0)ifright<0andleft<linear_i64_min()-right",
    "return(true,left+right)",
)
add_positions = [add_fn.find(fragment) for fragment in add_order]
if any(position < 0 for position in add_positions) or add_positions != sorted(add_positions):
    raise SystemExit("signed addition must reject both overflow directions before returning its sum")

sub_fn = compact(function_section(source_text, "linear_sub_safe"))
sub_order = (
    "return(false,0)ifright>0andleft<linear_i64_min()+right",
    "return(false,0)ifright<0andleft>linear_i64_max()+right",
    "return(true,left-right)",
)
sub_positions = [sub_fn.find(fragment) for fragment in sub_order]
if any(position < 0 for position in sub_positions) or sub_positions != sorted(sub_positions):
    raise SystemExit("signed subtraction must reject both overflow directions before returning its difference")

folder = compact(function_section(INDEX_FOLD.read_text(), "resolve_fold_binary"))
if "returnlinear_arith_safe(left,operator,right)" not in folder:
    raise SystemExit("constant-index folding no longer delegates checked arithmetic to linear_arith_safe")
arithmetic_dispatch = compact(function_section(source_text, "linear_arith_safe"))
for fragment in (
    "returnlinear_add_safe(left,right)ifoperator==TokenKind.Plus",
    "returnlinear_sub_safe(left,right)ifoperator==TokenKind.Minus",
):
    if fragment not in arithmetic_dispatch:
        raise SystemExit("linear arithmetic dispatch no longer delegates plus/minus to the checked helpers")

positive_names = {
    "safe_positive_add", "safe_negative_add", "safe_zero_add",
    "safe_positive_sub", "safe_negative_sub", "safe_zero_sub",
}
negative_names = {
    "false_positive_add_guard_accepts_overflow",
    "false_negative_add_guard_accepts_underflow",
    "false_positive_sub_guard_accepts_underflow",
    "false_negative_sub_guard_accepts_overflow",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_shapes = {
    "safe_positive_add": "requires right > 0 requires left <= 9223372036854775807 - right ensure result == left + right return left + right",
    "safe_negative_add": "requires right < 0 requires left >= (0 - 9223372036854775807 - 1) - right ensure result == left + right return left + right",
    "safe_zero_add": "requires right == 0 ensure result == left return left + right",
    "safe_positive_sub": "requires right > 0 requires left >= (0 - 9223372036854775807 - 1) + right ensure result == left - right return left - right",
    "safe_negative_sub": "requires right < 0 requires left <= 9223372036854775807 + right ensure result == left - right return left - right",
    "safe_zero_sub": "requires right == 0 ensure result == left return left - right",
}
positive_text = POSITIVE.read_text()
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer proves its accepted arithmetic branch")
negative_shapes = {
    "false_positive_add_guard_accepts_overflow": "requires right > 0 and left > 9223372036854775807 - right ensure result == true return left <= 9223372036854775807 - right",
    "false_negative_add_guard_accepts_underflow": "requires right < 0 and left < (0 - 9223372036854775807 - 1) - right ensure result == true return left >= (0 - 9223372036854775807 - 1) - right",
    "false_positive_sub_guard_accepts_underflow": "requires right > 0 and left < (0 - 9223372036854775807 - 1) + right ensure result == true return left >= (0 - 9223372036854775807 - 1) + right",
    "false_negative_sub_guard_accepts_overflow": "requires right < 0 and left > 9223372036854775807 + right ensure result == true return left <= 9223372036854775807 + right",
}
negative_text = NEGATIVE.read_text()
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges its overflow-boundary claim")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("checked addition/subtraction proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, INDEX_FOLD, POSITIVE, NEGATIVE,
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 12
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "linear add/sub proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 20 and negative["summary"]["proven"] == 16
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "signed addition/subtraction exact-result contracts under each production overflow guard",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
