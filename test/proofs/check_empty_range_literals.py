"""Admit source-linked range-emptiness laws for literal integer bounds."""
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
SOURCE = ROOT / "src/semantic/check_empty_range.elisa"
POSITIVE = HERE / "empty_range_literals.elisa"
NEGATIVE = HERE / "empty_range_literals_rejected.elisa"

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
empty_fn = compact(function_section(source_text, "is_empty_range"))
branch_map = {
    "RangeLt": "a>=b",
    "RangeLe": "a>b",
    "RangeGt": "a<=b",
}
source_branches = re.findall(
    r"(?m)^\s*TokenKind\.(RangeLt|RangeLe|RangeGt):\s*\n\s*return\s+([^\n]+)",
    function_section(source_text, "is_empty_range"),
)
all_token_branches = re.findall(r"TokenKind\.([A-Za-z0-9]+):", function_section(source_text, "is_empty_range"))
if all_token_branches != ["RangeLt", "RangeLe", "RangeGt"]:
    raise SystemExit("is_empty_range gained or removed an operator branch")
if len(source_branches) != len(branch_map) or {name: compact(expr) for name, expr in source_branches} != branch_map:
    raise SystemExit("literal range emptiness token branches changed")
if "Expr.Binary(lo,op,hi,line)" not in empty_fn or "Expr.IntLit(a,_)" not in empty_fn or "Expr.IntLit(b,_)" not in empty_fn:
    raise SystemExit("empty-range arithmetic is no longer limited to binary expressions with two integer literals")
if "returnfalse" not in empty_fn:
    raise SystemExit("unrecognized operators or nonliteral bounds must remain conservatively nonempty")

proof_names = {
    "proof_empty_lt", "lt_empty_if_reversed", "lt_nonempty_if_ordered",
    "proof_empty_le", "le_empty_if_reversed", "le_nonempty_if_ordered_or_equal",
    "proof_empty_gt", "gt_empty_if_forward_or_equal", "gt_nonempty_if_reversed",
}
negative_names = {
    "false_lt_nonempty_is_empty", "false_le_equality_is_empty", "false_gt_reverse_is_empty",
}
for path, expected in ((POSITIVE, proof_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

proof_shapes = {
    "proof_empty_lt": compact("ensure result == (a >= b) return a >= b"),
    "proof_empty_le": compact("ensure result == (a > b) return a > b"),
    "proof_empty_gt": compact("ensure result == (a <= b) return a <= b"),
    "lt_empty_if_reversed": compact("requires a >= b ensure result == true return proof_empty_lt(a, b)"),
    "lt_nonempty_if_ordered": compact("requires a < b ensure result == true return not proof_empty_lt(a, b)"),
    "le_empty_if_reversed": compact("requires a > b ensure result == true return proof_empty_le(a, b)"),
    "le_nonempty_if_ordered_or_equal": compact("requires a <= b ensure result == true return not proof_empty_le(a, b)"),
    "gt_empty_if_forward_or_equal": compact("requires a <= b ensure result == true return proof_empty_gt(a, b)"),
    "gt_nonempty_if_reversed": compact("requires a > b ensure result == true return not proof_empty_gt(a, b)"),
}
positive_text = POSITIVE.read_text()
for name, shape in proof_shapes.items():
    actual = compact(function_section(positive_text, name))
    if shape not in actual:
        raise SystemExit(f"{name} no longer proves its intended source-linked range property")
negative_shapes = {
    "false_lt_nonempty_is_empty": compact("requires a < b ensure result == true return proof_empty_lt(a, b)"),
    "false_le_equality_is_empty": compact("requires a == b ensure result == true return proof_empty_le(a, b)"),
    "false_gt_reverse_is_empty": compact("requires a > b ensure result == true return proof_empty_gt(a, b)"),
}
negative_text = NEGATIVE.read_text()
for name, shape in negative_shapes.items():
    actual = compact(function_section(negative_text, name))
    if shape not in actual:
        raise SystemExit(f"{name} no longer challenges the proved comparison boundary")

walk_fn = compact(function_section(source_text, "check_empty_range_statements"))
for fragment in (
    "Stmt.For(bind,variables,iterable,body,line):",
    "ifis_empty_range(iterable):",
    "DiagnosticKind.EmptyRange",
    "check_empty_range_statements(body,table)",
):
    if fragment not in walk_fn:
        raise SystemExit("range emptiness result is no longer reported while walking for-loop bodies")
decl_fn = compact(function_section(source_text, "check_empty_range"))
for fragment in ("Decl.Func(", "Decl.Module(", "Decl.Scoped(", "check_empty_range(body,table)"):
    if fragment not in decl_fn:
        raise SystemExit("empty-range checking no longer walks nested declarations")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("empty-range proofs require a strict proof build")
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
assert positive["summary"]["declarations"] == len(proof_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 18
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "empty-range proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == proof_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(proof_names) + len(negative_names)
assert negative["summary"]["obligations"] == 24 and negative["summary"]["proven"] == 21
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "literal <, <= and > empty-range conditions, including exact and reversed endpoints",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
