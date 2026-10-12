"""Admit source-linked proofs of the exact value-threading mutator set."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "value_thread_mutating_method.elisa"
NEGATIVE = HERE / "value_thread_mutating_method_rejected.elisa"
SOURCE = ROOT / "src/parser/ast_value_thread_mutating_method.elisa"
INTEGRATION = ROOT / "src/parser/ast_value_threading_mark.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_chunk(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\s*\(", text)
    if not match:
        raise AssertionError(f"function not found: {name}")
    following = re.search(r"(?m)^[ \t]*def ", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def pattern_names(chunk: str) -> list[str]:
    dispatch = re.search(
        r"return\s+when\s+method:\s*\n(.*?)^[ \t]*_\s*->\s*false\s*$",
        chunk,
        re.DOTALL | re.MULTILINE,
    )
    if not dispatch:
        raise AssertionError("production mutator classifier lost its exhaustive match")
    arms = [line.strip() for line in dispatch.group(1).splitlines() if line.strip()]
    names = []
    for arm in arms:
        if not re.fullmatch(r'"[^"\\]+"(?:\s*\|\s*"[^"\\]+")*\s*->\s*true', arm):
            raise AssertionError("production mutator match contains a non-literal or non-true arm")
        names.extend(re.findall(r'"([^"\\]+)"', arm))
    return names


source_text = SOURCE.read_text()
source_classifier = function_chunk(source_text, "is_mutating_method")
production_names = pattern_names(source_classifier)
if not production_names or len(production_names) != len(set(production_names)):
    raise AssertionError("production mutator match is empty or contains duplicate patterns")
source_contract = re.search(
    r"ensure\s+result\s*==\s*\(\s*when\s+method:\s*(.*?)^[ \t]*_\s*->\s*false\s*\)",
    source_classifier,
    re.DOTALL | re.MULTILINE,
)
if not source_contract:
    raise AssertionError("production classifier lost its exact-set pattern postcondition")
source_contract_names = re.findall(r'"([^"\\]+)"', source_contract.group(1))
if source_contract_names != production_names:
    raise AssertionError("production classifier contract differs from its match arms")
integration_text = INTEGRATION.read_text()
integration_classifier = function_chunk(integration_text, "value_thread_mutating_method")
if "AstValueThreadMutatingMethod::is_mutating_method(method)" not in integration_classifier:
    raise AssertionError("value-threading AST helper no longer delegates to the proved classifier")
if 'include "./ast_value_thread_mutating_method.elisa"' not in integration_text:
    raise AssertionError("value-threading AST integration no longer imports the proved classifier")

positive_text = POSITIVE.read_text()
proof_theorem = function_chunk(positive_text, "source_mutating_method_matches_exact_set")
contract = re.search(
    r"ensure\s+result\s*==\s*\(\s*when\s+method:\s*(.*?)^[ \t]*_\s*->\s*false\s*\)",
    proof_theorem,
    re.DOTALL | re.MULTILINE,
)
if not contract:
    raise AssertionError("source-linked theorem lost its exact closed-set pattern contract")
proof_names = re.findall(r'"([^"\\]+)"', contract.group(1))
if proof_names != production_names:
    raise AssertionError("proof contract differs from the ordered production match patterns")
if "return AstValueThreadMutatingMethod::is_mutating_method(method)" not in proof_theorem:
    raise AssertionError("universal theorem no longer calls the production classifier")
if 'include "../../src/parser/ast_value_thread_mutating_method.elisa"' not in positive_text:
    raise AssertionError("positive proof no longer includes the production classifier")
if 'include "./value_thread_mutating_method.elisa"' not in NEGATIVE.read_text():
    raise AssertionError("negative controls no longer import the positive source-linked proof")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("value-thread mutator proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, INTEGRATION])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", *source_closure,
]
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {"value_thread_mutating_method", "source_mutating_method_matches_exact_set",
        "known_mutating_method_is_recognized"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "read_only_method_must_not_be_mutating"),
    ("ensure-unproven", "unrelated_method_must_not_be_mutating"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact mutating-method set used by AST value threading",
    "mutating_methods": production_names,
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [finding["name"] for finding in negative["findings"]],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
