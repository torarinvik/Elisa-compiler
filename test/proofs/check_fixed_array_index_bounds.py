"""Admit source-linked fixed-array bounds and checked-access guard laws."""
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
SOURCE = ROOT / "src/semantic/check_index_out_of_bounds.elisa"
POSITIVE = HERE / "fixed_array_index_bounds.elisa"
NEGATIVE = HERE / "fixed_array_index_bounds_rejected.elisa"

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
walk = compact(function_section(source_text, "walk_expression_for_index_out_of_bounds"))
for fragment in (
    "Expr.Index(object,index,line):",
    "Expr.Ident(arr_name,_):",
    "resolve_known_int(index,table,has_index,actual_index)",
    "iffound_index>=0andhas_index:",
    "checked:bool=anyginchecked_get_lineswhereg==line.line",
    "actual_count<-actual_index.u32()ifactual_index>=0",
    "(actual_index>=expected_sizeoractual_index<0)andnotchecked",
    "DiagnosticKind.IndexOutOfBounds",
):
    if fragment not in walk:
        raise SystemExit("fixed-array index diagnosis no longer follows the source-linked i64 guard")

positive_names = {
    "proof_reports_index_out_of_bounds",
    "in_range_index_is_not_reported",
    "negative_index_is_reported",
    "index_at_or_above_extent_is_reported",
    "checked_get_suppresses_bounds_diagnostic",
    "wide_index_is_checked_before_display_narrowing",
}
negative_names = {
    "false_in_range_index_is_reported",
    "false_checked_access_reports_oob",
    "false_wide_index_is_not_reported",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

expected_shapes = {
    "proof_reports_index_out_of_bounds": "ensure result == ((index >= size or index < 0) and not checked) return (index >= size or index < 0) and not checked",
    "in_range_index_is_not_reported": "requires index >= 0 and index < size ensure result == true return not proof_reports_index_out_of_bounds(index, size, false)",
    "negative_index_is_reported": "requires index < 0 ensure result == true return proof_reports_index_out_of_bounds(index, size, false)",
    "index_at_or_above_extent_is_reported": "requires index >= size ensure result == true return proof_reports_index_out_of_bounds(index, size, false)",
    "checked_get_suppresses_bounds_diagnostic": "requires checked ensure result == true return not proof_reports_index_out_of_bounds(index, size, checked)",
    "wide_index_is_checked_before_display_narrowing": "requires index > 4294967295 and size <= 4294967295 ensure result == true return proof_reports_index_out_of_bounds(index, size, false)",
}
positive_text = POSITIVE.read_text()
for name, shape in expected_shapes.items():
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer states its intended bounds property")
negative_shapes = {
    "false_in_range_index_is_reported": "requires index >= 0 and index < size ensure result == true return proof_reports_index_out_of_bounds(index, size, false)",
    "false_checked_access_reports_oob": "requires checked ensure result == true return proof_reports_index_out_of_bounds(index, size, checked)",
    "false_wide_index_is_not_reported": "requires index > 4294967295 and size <= 4294967295 ensure result == true return not proof_reports_index_out_of_bounds(index, size, false)",
}
negative_text = NEGATIVE.read_text()
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges the expected bounds invariant")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("fixed-array index proofs require a strict proof build")
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 12
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "fixed-array index proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 18 and negative["summary"]["proven"] == 15
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "fixed-array i64 index guard, checked-access suppression, and comparison before u32 narrowing",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
