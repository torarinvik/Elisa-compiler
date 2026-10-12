"""Admit the signed multiplication overflow guards in Semantic's constant arithmetic."""
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
POSITIVE = HERE / "linear_mul_overflow.elisa"
NEGATIVE = HERE / "linear_mul_overflow_rejected.elisa"

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

positive_text = compact(POSITIVE.read_text())
if "constI64_MAX:i64=9223372036854775807" not in positive_text or \
        "constI64_MIN:i64=0-I64_MAX-1" not in positive_text:
    raise SystemExit("proof bounds must use named constants anchored to the source i64 extrema")

multiply = compact(function_section(source_text, "linear_mul_safe"))
ordered_guards = (
    "return(true,0)ifleft==0orright==0",
    "return(true,right)ifleft==1",
    "return(true,left)ifright==1",
    "ifleft==-1:",
    "return(false,0)ifright==linear_i64_min()",
    "return(true,0-right)",
    "ifright==-1:",
    "return(false,0)ifleft==linear_i64_min()",
    "return(true,0-left)",
    "ifleft>0:",
    "return(false,0)ifright>0andleft>linear_i64_max()/right",
    "return(false,0)ifright<0andright<linear_i64_min()/left",
    "else:",
    "return(false,0)ifright>0andleft<linear_i64_min()/right",
    "return(false,0)ifright<0andleft<linear_i64_max()/right",
    "return(true,left*right)",
)
guard_positions = [multiply.find(fragment) for fragment in ordered_guards]
if any(position < 0 for position in guard_positions) or guard_positions != sorted(guard_positions):
    raise SystemExit("multiplication must handle zero/units, reject MIN * -1, guard all sign quadrants, then return the product")
if any(multiply.count(fragment) != 1 for fragment in ordered_guards):
    raise SystemExit("multiplication guard branches must occur exactly once")

arithmetic_dispatch = compact(function_section(source_text, "linear_arith_safe"))
if "returnlinear_mul_safe(left,right)ifoperator==TokenKind.Star" not in arithmetic_dispatch:
    raise SystemExit("linear arithmetic dispatch no longer delegates multiplication to linear_mul_safe")
folder = compact(function_section(INDEX_FOLD.read_text(), "resolve_fold_binary"))
if "returnlinear_arith_safe(left,operator,right)" not in folder:
    raise SystemExit("constant-index folding no longer delegates checked arithmetic to linear_arith_safe")

positive_names = {
    "safe_mul_positive_positive", "safe_mul_positive_negative",
    "safe_mul_negative_positive", "safe_mul_negative_negative",
    "zero_product_case", "left_one_product_case", "right_one_product_case",
    "left_negative_one_product_case", "right_negative_one_product_case",
    "minimum_left_times_negative_one_is_rejected",
    "negative_one_times_minimum_right_is_rejected",
}
negative_names = {
    "false_positive_product_passes_bound",
    "false_positive_negative_product_passes_bound",
    "false_negative_positive_product_passes_bound",
    "false_negative_product_passes_bound",
    "false_claim_minimum_left_product_is_safe",
    "false_claim_minimum_right_product_is_safe",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_shapes = {
    "safe_mul_positive_positive": "requires left > 0 and right > 0 requires left <= I64_MAX / right ensure result == left * right return left * right",
    "safe_mul_positive_negative": "requires left > 0 and right < 0 requires right >= I64_MIN / left ensure result == left * right return left * right",
    "safe_mul_negative_positive": "requires left < 0 and right > 0 requires left >= I64_MIN / right ensure result == left * right return left * right",
    "safe_mul_negative_negative": "requires left < 0 and right < 0 requires left >= I64_MAX / right ensure result == left * right return left * right",
    "zero_product_case": "requires left == 0 or right == 0 ensure result == 0 return 0",
    "left_one_product_case": "requires left == 1 ensure result == right return right",
    "right_one_product_case": "requires right == 1 ensure result == left return left",
    "left_negative_one_product_case": "requires left == (0 - 1) and right != I64_MIN ensure result == (0 - right) return 0 - right",
    "right_negative_one_product_case": "requires right == (0 - 1) and left != I64_MIN ensure result == (0 - left) return 0 - left",
    "minimum_left_times_negative_one_is_rejected": "requires left == (0 - I64_MAX - 1) and right == (0 - 1) ensure result == false return left != (0 - I64_MAX - 1)",
    "negative_one_times_minimum_right_is_rejected": "requires left == (0 - 1) and right == (0 - I64_MAX - 1) ensure result == false return right != (0 - I64_MAX - 1)",
}
positive_source = POSITIVE.read_text()
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(positive_source, name)):
        raise SystemExit(f"{name} no longer proves its intended accepted multiplication branch")

negative_shapes = {
    "false_positive_product_passes_bound": "requires left > 0 and right > 0 and left > I64_MAX / right ensure result == true return left <= I64_MAX / right",
    "false_positive_negative_product_passes_bound": "requires left > 0 and right < 0 and right < I64_MIN / left ensure result == true return right >= I64_MIN / left",
    "false_negative_positive_product_passes_bound": "requires left < 0 and right > 0 and left < I64_MIN / right ensure result == true return left >= I64_MIN / right",
    "false_negative_product_passes_bound": "requires left < 0 and right < 0 and left < I64_MAX / right ensure result == true return left >= I64_MAX / right",
    "false_claim_minimum_left_product_is_safe": "requires left == (0 - I64_MAX - 1) and right == (0 - 1) ensure result == true return left != (0 - I64_MAX - 1)",
    "false_claim_minimum_right_product_is_safe": "requires left == (0 - 1) and right == (0 - I64_MAX - 1) ensure result == true return right != (0 - I64_MAX - 1)",
}
negative_text = NEGATIVE.read_text()
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges an overflowing sign-quadrant boundary")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("checked multiplication proofs require a strict proof build")
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
assert positive["summary"]["declarations"] == len(positive_names) + 2
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 22
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "linear multiplication proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + 2 + len(negative_names)
assert negative["summary"]["obligations"] == 34 and negative["summary"]["proven"] == 28
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "signed multiplication exact-result contracts under production sign-quadrant guards, zero/unit cases, and both MIN-times-negative-one rejection paths",
    "positive_obligations": positive["summary"]["proven"],
    "false_overflow_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
