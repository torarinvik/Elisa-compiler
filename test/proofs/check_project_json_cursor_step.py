"""Admit the signed-scalar bounds/progress model for JSON whitespace scanning."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/driver/project_json_parse.elisa"
SPACE_SOURCE = ROOT / "src/driver/project.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
POSITIVE = HERE / "project_json_cursor_step.elisa"
NEGATIVE = HERE / "project_json_cursor_step_rejected.elisa"

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
skip_ws = compact(function_section(source, "json_skip_ws"))
steps = (
    "whilecursor.position<data.count|cursor,data|:",
    "breakifnotbytes_is_space(data[cursor.position])",
    "cursor.position<-cursor.position+1.usize()",
)
positions = [skip_ws.find(step) for step in steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("JSON whitespace scan no longer guards its byte read and advances one byte only after whitespace")

project_source = SPACE_SOURCE.read_text()
if 'include "./project_json_parse.elisa"' not in project_source or \
        'include "./project.elisa"' not in DRIVER.read_text():
    raise SystemExit("JSON cursor-step source is no longer included by the production compiler driver")
space = compact(function_section(project_source, "bytes_is_space"))
space_values = (
    "byte==ProjectSystemWhitespaceByte::ASCII_SPACE",
    "byte==ProjectSystemWhitespaceByte::ASCII_HORIZONTAL_TAB",
    "byte==ProjectSystemWhitespaceByte::ASCII_LINE_FEED",
    "byte==ProjectSystemWhitespaceByte::ASCII_CARRIAGE_RETURN",
)
if not all(value in space for value in space_values) or "return(" not in space:
    raise SystemExit("JSON whitespace scan no longer delegates to the project's exact ASCII whitespace predicate")

positive_names = {
    "json_skip_ws_step",
}
negative_names = {
    "false_claim_whitespace_at_end_advances",
    "false_claim_non_whitespace_byte_is_consumed",
}


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declaration_names(POSITIVE) != positive_names:
    raise SystemExit("JSON cursor-step positive proof inventory changed")
if declaration_names(NEGATIVE) != negative_names or \
        'include "./project_json_cursor_step.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("JSON cursor-step negative controls changed")

proof_step = compact(function_section(POSITIVE.read_text(), "json_skip_ws_step"))
required_contracts = (
    "defjson_skip_ws_step(length:i64,position:i64,is_space:bool)->i64:",
    "requireslength>=0andposition>=0andposition<=length",
    "ensureresult==(position+1ifposition<lengthandis_spaceelseposition)",
    "ensureresult>=0",
    "ensureresult<=length",
    "ensureresult>=position",
    "ensure(position<lengthandis_space)impliesresult>position",
    "ensure(position<lengthandis_space)implieslength-result==length-position-1",
    "ensure(position==lengthornotis_space)impliesresult==position",
    "returnposition+1ifposition<lengthandis_spaceelseposition",
)
if not all(contract in proof_step for contract in required_contracts):
    raise SystemExit("JSON cursor-step proof no longer states the bounded one-byte transition laws")
negative_text = compact(NEGATIVE.read_text())
required_false_claims = (
    "requireslength>=0andposition==lengthandis_spaceensureresult==truereturn(position+1ifposition<lengthandis_spaceelseposition)==position+1",
    "requireslength>0andposition>=0andposition<lengthandnotis_spaceensureresult==truereturn(position+1ifposition<lengthandis_spaceelseposition)==position+1",
)
if not all(claim in negative_text for claim in required_false_claims):
    raise SystemExit("JSON cursor-step negative controls no longer challenge the boundary and stop cases")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("ProjectSystem JSON cursor-step proofs require a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    SPACE_SOURCE,
    DRIVER,
    POSITIVE,
    NEGATIVE,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert report["summary"]["semantic_diagnostics"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "JSON cursor-step proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == negative["summary"]["proven"] + len(negative_names)
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "signed i64 model of JSON whitespace cursor-step preservation, progress, and stopping behavior",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
