"""Admit the constant-index folder's division and remainder precondition proofs."""
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
FOLD_SOURCE = ROOT / "src/semantic/check_index_out_of_bounds.elisa"
MIN_SOURCE = ROOT / "src/semantic/check_ensure_strict.elisa"
POSITIVE = HERE / "index_constant_division_guards.elisa"
NEGATIVE = HERE / "index_constant_division_guards_rejected.elisa"

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


fold_text = FOLD_SOURCE.read_text()
fold_fn = compact(function_section(fold_text, "resolve_fold_binary"))
ordered = (
    "ifoperator==TokenKind.Slashoroperator==TokenKind.Percent:",
    "return(false,0)ifright==0",
    "return(false,0)ifleft==linear_i64_min()andright==-1",
    "return(true,left/right)ifoperator==TokenKind.Slash",
    "return(true,left%right)",
)
positions = [fold_fn.find(fragment) for fragment in ordered]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("division and remainder folding must reject both invalid operands before evaluating either operator")
minimum_fn = compact(function_section(MIN_SOURCE.read_text(), "linear_i64_min"))
if minimum_fn.count("return0-9223372036854775807-1") != 1:
    raise SystemExit("overflow guard no longer uses the i64 minimum sentinel")
known_int_fn = compact(function_section(fold_text, "resolve_known_int"))
for fragment in (
    "folded:(known:bool,value:i64)=resolve_fold_binary(left_value,operator,right_value)",
    "found<-left_foundandright_foundandsupportedandsafe_divisorandfolded.known",
):
    if fragment not in known_int_fn:
        raise SystemExit("invalid division or remainder operands can enter the constant-index model")

positive_names = {
    "proof_divisor_is_nonzero", "zero_divisor_is_rejected", "nonzero_divisor_passes_first_guard",
    "proof_min_div_negative_one_pair", "min_divided_by_negative_one_is_rejected",
    "different_left_excludes_overflow_pair", "different_right_excludes_overflow_pair",
    "safe_division_pair_does_not_match_overflow",
}
negative_names = {
    "false_zero_divisor_passes_guard", "false_nonzero_divisor_is_rejected",
    "false_min_overflow_pair_is_safe",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_shapes = {
    "proof_divisor_is_nonzero": "ensure result == (right != 0) return right != 0",
    "zero_divisor_is_rejected": "requires right == 0 ensure result == true return not proof_divisor_is_nonzero(right)",
    "nonzero_divisor_passes_first_guard": "requires right != 0 ensure result == true return proof_divisor_is_nonzero(right)",
    "proof_min_div_negative_one_pair": "ensure result == (left == minimum and right == (0 - 1)) return left == minimum and right == (0 - 1)",
    "min_divided_by_negative_one_is_rejected": "requires left == minimum and right == (0 - 1) ensure result == true return proof_min_div_negative_one_pair(left, right, minimum)",
    "different_left_excludes_overflow_pair": "requires left != minimum ensure result == true return not proof_min_div_negative_one_pair(left, right, minimum)",
    "different_right_excludes_overflow_pair": "requires right != (0 - 1) ensure result == true return not proof_min_div_negative_one_pair(left, right, minimum)",
    "safe_division_pair_does_not_match_overflow": "requires left != minimum or right != (0 - 1) ensure result == true return not proof_min_div_negative_one_pair(left, right, minimum)",
}
positive_text = POSITIVE.read_text()
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer states its intended operand-safety law")
negative_shapes = {
    "false_zero_divisor_passes_guard": "requires right == 0 ensure result == true return proof_divisor_is_nonzero(right)",
    "false_nonzero_divisor_is_rejected": "requires right != 0 ensure result == true return not proof_divisor_is_nonzero(right)",
    "false_min_overflow_pair_is_safe": "requires left == minimum and right == (0 - 1) ensure result == true return not proof_min_div_negative_one_pair(left, right, minimum)",
}
negative_text = NEGATIVE.read_text()
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges an invalid-operand guard")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("index-division guard proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", FOLD_SOURCE, MIN_SOURCE,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE]),
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 16
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "index-division proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 22 and negative["summary"]["proven"] == 19
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "zero-divisor and i64-minimum/-1 guards before signed constant division and remainder",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
