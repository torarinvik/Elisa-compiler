"""Admit overflow-safe, source-bound JSON byte-span indexing proofs."""
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
SOURCE = ROOT / "src/driver/project_json_parse.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
BASE_PROOF = HERE / "frontend_ir_decode_bounds.elisa"
POSITIVE = HERE / "project_json_span_bounds.elisa"
NEGATIVE = HERE / "project_json_span_bounds_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():], re.MULTILINE)
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


source = SOURCE.read_text()
span_body = function_section(source, "json_span_is")
span = compact("\n".join(line.split("#", 1)[0] for line in span_body.splitlines()))
guard_order = (
    "falsereturnifstart>data.count",
    "falsereturniflength>data.count-start",
    "forindexin0..<length|data,name,start|:",
    "data[start+index]",
)
positions = [span.find(fragment) for fragment in guard_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("JSON span comparison no longer validates remaining capacity before indexed reads")
if "start+length" in span:
    raise SystemExit("JSON span comparison reintroduced a potentially wrapping endpoint sum")

if 'include "./project_json_parse.elisa"' not in PROJECT.read_text() or \
        'include "./project.elisa"' not in DRIVER.read_text():
    raise SystemExit("JSON span reader is no longer included by the production compiler driver")

base_names = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", BASE_PROOF.read_text()))
required_base = {
    "bounded_sum_fits_data",
    "span_length_beyond_remaining_fails",
    "span_start_beyond_data_fails",
}
if not required_base <= base_names:
    raise SystemExit("JSON span proof no longer imports the usize span arithmetic lemmas")
if 'include "./frontend_ir_decode_bounds.elisa"' not in POSITIVE.read_text():
    raise SystemExit("JSON span proof no longer includes its checked usize arithmetic foundation")

positive_names = {"json_span_index_is_inside_data"}
negative_names = {
    "false_claim_start_past_data_is_accepted",
    "false_claim_length_past_remaining_data_is_accepted",
}


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declaration_names(POSITIVE) != positive_names:
    raise SystemExit("JSON span positive proof inventory changed")
if declaration_names(NEGATIVE) != negative_names or \
        'include "./project_json_span_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("JSON span negative controls changed")

proof_text = compact(function_section(POSITIVE.read_text(), "json_span_index_is_inside_data"))
required_proof = (
    "defjson_span_index_is_inside_data(start:usize,length:usize,total:usize,index:usize)->bool:",
    "requiresstart<=total",
    "requireslength<=total-start",
    "requiresindex<length",
    "ensureresult==true",
    "returnstart+index<total",
)
if not all(fragment in proof_text for fragment in required_proof):
    raise SystemExit("JSON span proof no longer proves every loop index lies within the accepted span")

negative_text = compact(NEGATIVE.read_text())
required_false_claims = (
    "requiresstart>totalensureresult==truereturnstart<=total",
    "requiresstart<=totalandlength>total-startensureresult==truereturnlength<=total-start",
)
if not all(fragment in negative_text for fragment in required_false_claims):
    raise SystemExit("JSON span negative controls no longer challenge both overflow-safe guards")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("JSON span proofs require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    PROJECT,
    DRIVER,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert report["summary"]["semantic_diagnostics"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(base_names) + len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "JSON span proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(base_names) + len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == negative["summary"]["proven"] + len(negative_names)
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "overflow-safe JSON span guards imply every indexed byte is inside data.count",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
