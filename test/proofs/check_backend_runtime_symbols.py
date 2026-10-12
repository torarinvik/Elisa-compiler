"""Admit source-linked proofs of the backend runtime-symbol policy."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "backend_runtime_symbols.elisa"
NEGATIVE = HERE / "backend_runtime_symbols_rejected.elisa"
SOURCE = ROOT / "src/backend/codegen_runtime_symbols.elisa"
CALL_SITES = ROOT / "src/backend/codegen_declines.elisa"
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


def function_chunk(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\s*\(", text)
    if not match:
        raise AssertionError(f"function not found: {name}")
    following = re.search(r"(?m)^[ \t]*def ", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def contract_names(chunk: str) -> list[str]:
    contract = re.search(
        r"ensure\s+result\s*==\s*\(\s*when\s+name:\s*\n"
        r"(.*?)^[ \t]*_\s*->\s*false\s*\n[ \t]*\)",
        chunk,
        re.DOTALL | re.MULTILINE,
    )
    if contract:
        arms = [line.strip() for line in contract.group(1).splitlines() if line.strip()]
        pattern_arm = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"(?:\s*\|\s*"([^"\\]*(?:\\.[^"\\]*)*)")*\s*->\s*true')
        names = []
        for arm in arms:
            if not pattern_arm.fullmatch(arm):
                raise AssertionError("closed-set contract must map literal patterns to true")
            names.extend(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', arm))
        return names
    # Keep simple singleton policies readable; multi-name policies above must use patterns.
    contract = re.search(r"ensure\s+result\s*==(.+?)(?=\n[ \t]*(?:can\b|return\b))", chunk, re.DOTALL)
    if not contract:
        raise AssertionError("closed-set theorem has no result contract")
    return re.findall(r'\bname\s*==\s*"([^"\\]*(?:\\.[^"\\]*)*)"', contract.group(1))


def classifier_names(chunk: str) -> list[str]:
    dispatch = re.search(r"return\s+when\s+name:\s*\n(.*?)(?=^[ \t]*_\s*->\s*false\s*$)", chunk, re.DOTALL | re.MULTILINE)
    if not dispatch:
        direct_return = re.search(r"(?m)^[ \t]*return (.+)$", chunk)
        if not direct_return:
            raise AssertionError("production classifier has no closed name match")
        return re.findall(r'\bname\s*==\s*"([^"\\]*(?:\\.[^"\\]*)*)"', direct_return.group(1))
    return re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', dispatch.group(1))


source_text = SOURCE.read_text()
call_site_text = CALL_SITES.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

classifier_theorems = {
    "is_allocator_symbol": "allocator_symbols_match_the_exact_set",
    "is_string_runtime_symbol": "string_runtime_symbols_match_the_exact_set",
    "is_trace_runtime_symbol": "trace_runtime_symbols_match_the_exact_set",
    "is_aos_store_runtime_symbol": "aos_store_runtime_symbols_match_the_exact_set",
    "is_packed_store_runtime_symbol": "packed_store_runtime_symbols_match_the_exact_set",
    "is_trace_callback": "trace_callback_policy_is_exact",
    "is_runtime_external_only": "runtime_external_only_policy_is_exact",
}
all_policy_names: set[str] = set()
for classifier, theorem in classifier_theorems.items():
    source_chunk = function_chunk(source_text, classifier)
    theorem_chunk = function_chunk(positive_text, theorem)
    contract = contract_names(source_chunk)
    arms = classifier_names(source_chunk)
    proof_contract = contract_names(theorem_chunk)
    if len(contract) != len(set(contract)) or len(arms) != len(set(arms)):
        raise AssertionError(f"duplicate runtime-symbol arm in {classifier}")
    if set(contract) != set(arms):
        raise AssertionError(f"{classifier} contract and match arms classify different names")
    if set(proof_contract) != set(contract):
        raise AssertionError(f"{theorem} no longer states the exact production symbol set")
    if f"BackendRuntimeSymbols::{classifier}(name)" not in theorem_chunk:
        raise AssertionError(f"{theorem} no longer proves the production classifier")
    if classifier not in {"is_trace_callback", "is_runtime_external_only"}:
        all_policy_names.update(contract)

runtime_chunk = function_chunk(source_text, "is_runtime_provided")
runtime_theorem = function_chunk(positive_text, "runtime_symbol_policy_is_exact")
runtime_contract = re.search(r"ensure\s+result\s*==(.+?)(?=\n[ \t]*return\b)", runtime_theorem, re.DOTALL)
if not runtime_contract:
    raise AssertionError("runtime policy theorem lost its result contract")
runtime_contract_helpers = set(re.findall(r"BackendRuntimeSymbols::(is_[a-z_]+)\(name\)", runtime_contract.group(1)))
expected_helpers = {
    "is_allocator_symbol", "is_string_runtime_symbol", "is_trace_runtime_symbol",
    "is_aos_store_runtime_symbol", "is_packed_store_runtime_symbol",
}
if runtime_contract_helpers != expected_helpers:
    raise AssertionError("runtime policy theorem no longer covers the full production union")
if "BackendRuntimeSymbols::is_runtime_provided(name)" not in runtime_theorem:
    raise AssertionError("runtime policy theorem no longer calls the production union")
runtime_implementation = re.search(r"return (.+)$", runtime_chunk, re.MULTILINE)
if not runtime_implementation:
    raise AssertionError("production runtime policy has no return expression")
implementation_helpers = set(re.findall(r"is_[a-z_]+\(name\)", runtime_implementation.group(1)))
if implementation_helpers != {f"{name}(name)" for name in expected_helpers}:
    raise AssertionError("production runtime policy no longer matches the proved union")

inventory = function_chunk(positive_text, "every_runtime_symbol_is_classified")
inventory_names = set(re.findall(r'BackendRuntimeSymbols::is_runtime_provided\("([^"\\]+)"\)', inventory))
if inventory_names != all_policy_names:
    missing = sorted(all_policy_names - inventory_names)
    extra = sorted(inventory_names - all_policy_names)
    raise AssertionError(f"runtime symbol inventory differs from source sets; missing={missing}, extra={extra}")

for required in (
    'include "./codegen_runtime_symbols.elisa"',
    "return BackendRuntimeSymbols::is_runtime_provided(name)",
    "return BackendRuntimeSymbols::is_runtime_external_only(name)",
    "return BackendRuntimeSymbols::is_trace_callback(name)",
):
    if required not in call_site_text:
        raise AssertionError(f"backend call site no longer delegates to the proved policy: {required}")
if 'include "../../src/backend/codegen_runtime_symbols.elisa"' not in positive_text:
    raise AssertionError("positive proof no longer includes the production classifier")
if 'include "./backend_runtime_symbols.elisa"' not in negative_text:
    raise AssertionError("negative controls no longer include the source-linked proof")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("backend runtime-symbol proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    *source_include_closure([POSITIVE, NEGATIVE, CALL_SITES]),
    BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, CALL_SITES, POSITIVE, NEGATIVE,
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
expected = set(classifier_theorems.values()) | {
    "runtime_symbol_policy_is_exact", "every_runtime_symbol_is_classified",
}
assert expected <= verified
assert all(row.get("verified") for row in positive["declaration_details"]
           if row["kind"] == "function")

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "unrecognized_symbol_must_not_be_runtime_provided"),
    ("ensure-unproven", "trace_counter_must_not_be_a_trace_callback"),
    ("ensure-unproven", "unrelated_helper_must_not_be_runtime_external_only"),
]

assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "backend runtime symbol whitelist, trace callbacks, and external-only policy",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [finding["name"] for finding in negative["findings"]],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
