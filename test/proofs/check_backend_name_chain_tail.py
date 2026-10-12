"""Replay the name-chain linear fallback's first-match refinement proof."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

if not __debug__:
    raise SystemExit("run without Python -O")


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/backend/codegen_name_chain_tail_policy.elisa"
CHAINS = ROOT / "src/backend/codegen_name_chains.elisa"
FACADE = ROOT / "src/backend/codegen.elisa"
POSITIVE = HERE / "backend_name_chain_tail.elisa"
NEGATIVE = HERE / "backend_name_chain_tail_rejected.elisa"

POSITIVE_NAMES = {
    "duplicate_names_select_the_first_row",
    "a_start_position_skips_earlier_matches",
    "a_missing_name_returns_the_absent_sentinel",
    "starting_at_the_end_returns_the_absent_sentinel",
    "starting_past_the_end_returns_the_absent_sentinel",
}
NEGATIVE_NAMES = {
    "a_duplicate_name_does_not_select_the_last_row",
    "a_missing_name_does_not_return_a_row",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^\s*def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


policy_text = POLICY.read_text()
expected_reference = """
ghost def first_match_from(names: darray[sview]&, name: sview, index: usize) -> i64:
    requires index <= names.count
    decreases names.count - index
    return -1 if index == names.count
    return index.i64() if names[index] == name
    return first_match_from(names, name, index + 1)
"""
if compact(function_section(policy_text, "first_match_from")) != compact(expected_reference):
    raise SystemExit("the recursive first-match specification changed without updating its proof")

expected_total_spec = """
ghost def first_match_spec(names: darray[sview]&, name: sview, start: usize) -> i64:
    return -1 if start > names.count
    return first_match_from(names, name, start)
"""
if compact(function_section(policy_text, "first_match_spec")) != compact(expected_total_spec):
    raise SystemExit("the total first-match specification no longer models out-of-range starts")

expected_scan = """
def first_match_index(names: darray[sview]&, name: sview, start: usize) -> i64:
    ensures result == first_match_spec(names, name, start)
    can Abort.Panic:
        return -1 if start > names.count
        index: mutable usize = start
        while index < names.count |index, names, name, start|:
            decreases names.count - index
            invariant start <= index and index <= names.count
            invariant first_match_from(names, name, index) == first_match_from(names, name, start)
            return index.i64() if names[index] == name
            index <- index + 1
        return -1
"""
if compact(function_section(policy_text, "first_match_index")) != compact(expected_scan):
    raise SystemExit("the iterative scan no longer refines the recursive first-match specification")

chain_text = CHAINS.read_text()
if 'include "./codegen_name_chain_tail_policy.elisa"' not in chain_text:
    raise SystemExit("the backend name-chain implementation no longer imports its verified fallback")
expected_tail = """
def name_chain_tail(names: darray[sview]&, name: sview, start: usize) -> i64 can[Abort.Panic]:
    can Abort.Panic:
        return BackendNameChainTailPolicy::first_match_index(names, name, start)
"""
if compact(function_section(chain_text, "name_chain_tail")) != compact(expected_tail):
    raise SystemExit("the production linear fallback no longer delegates to the proved first-match scan")
for caller in ("name_chain_from", "name_chain_first", "name_chain_next"):
    if "name_chain_tail(" not in compact(function_section(chain_text, caller)):
        raise SystemExit(f"{caller} no longer uses the proved linear fallback")
if 'include "./codegen_name_chains.elisa"' not in FACADE.read_text():
    raise SystemExit("the backend facade no longer imports the production name-chain index")
if 'include "../../src/backend/codegen_name_chain_tail_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proofs no longer include the production first-match policy")
if 'include "./backend_name_chain_tail.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer reuse the production first-match policy")
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("the name-chain first-match proof inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("the name-chain first-match proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", FACADE, CHAINS, POLICY,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert POSITIVE_NAMES | {"first_match_from", "first_match_spec", "first_match_index"} <= verified
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert NEGATIVE_NAMES.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "name-chain proof inputs changed during replay or provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "iterative name-chain tail lookup refines a recursive first-match specification",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
