"""Admit the decimal-digit narrowing used by the source unparser."""
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
SOURCE = ROOT / "src/driver/emit_fmt_expr.elisa"
POSITIVE = HERE / "decimal_digit_u8.elisa"
NEGATIVE = HERE / "decimal_digit_u8_rejected.elisa"

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


fmt = compact(function_section(SOURCE.read_text(), "fmt_expr"))
emitter_order = (
    "Expr.IntLit(fmt_int_value,fmt_int_pos):",
    "fmt_int_left:mutablei64=fmt_int_value",
    "whilefmt_int_left>0|fmt_int_left,fmt_int_digits|:",
    "fmt_int_digits.push((48+(fmt_int_left%10)).u8())",
    "fmt_int_left<-fmt_int_left/10",
)
positions = [fmt.find(fragment) for fragment in emitter_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("decimal digit narrowing must remain inside the positive IntLit loop and follow its divisor-10 update")
if fmt.count("fmt_int_digits.push((48+(fmt_int_left%10)).u8())") != 1:
    raise SystemExit("expected one source-unparser decimal digit narrowing site")

positive_names = {
    "decimal_digit_value_is_ascii", "positive_remainder_is_digit",
    "decimal_quotient_decreases",
}
negative_names = {"false_digit_is_at_most_eight", "false_digit_is_at_least_one"}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

positive_shapes = {
    "decimal_digit_value_is_ascii": "requires remaining > 0 ensure result >= 48 ensure result <= 57 return 48 + (remaining % 10)",
    "positive_remainder_is_digit": "requires remaining > 0 ensure result >= 0 ensure result < 10 return remaining % 10",
    "decimal_quotient_decreases": "requires remaining > 0 ensure result >= 0 ensure result < remaining return remaining / 10",
}
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(POSITIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer proves its decimal remainder bound")
negative_shapes = {
    "false_digit_is_at_most_eight": "requires remaining > 0 ensure result == true return 48 + (remaining % 10) <= 56",
    "false_digit_is_at_least_one": "requires remaining > 0 ensure result == true return 48 + (remaining % 10) >= 49",
}
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(NEGATIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer challenges one of the ASCII digit endpoints")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("decimal digit narrowing proofs require a strict proof build")
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 9
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "decimal digit proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 13 and negative["summary"]["proven"] == 11
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert negative_names.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "decimal remainder digits in the source unparser lie in ASCII '0'..'9' before narrowing to u8",
    "positive_obligations": positive["summary"]["proven"],
    "false_ascii_boundary_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
