"""Bind linear-probe safety proofs to dictionary and set lookup implementations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
COLLECTIONS = ROOT / "elisacore_std/collections.elisa"
POSITIVE = HERE / "runtime_dict_probe_bounds.elisa"
NEGATIVE = HERE / "runtime_dict_probe_bounds_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()
if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(
        rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}(?:\[[^\n]*?\])?\(", source
    ))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(
        rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\n]*?\])?\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source = COLLECTIONS.read_text()
contracts = {
    "arena_dict_find_index": (
        "ensure (m.capacity == 0 or m.items == null) implies (result.index == 0 and not result.found)",
        "ensure m.capacity > 0 implies result.index < m.capacity",
        "ensure result.found implies (m.capacity > 0 and m.items != null)",
    ),
    "arena_dict_find_cstr_view_index": (
        "ensure (m.capacity == 0 or m.items == null) implies (result.index == 0 and not result.found)",
        "ensure m.capacity > 0 implies result.index < m.capacity",
        "ensure result.found implies (m.capacity > 0 and m.items != null)",
    ),
    "arena_set_find_index": (
        "ensure (s.capacity == 0 or s.items == null) implies (result.index == 0 and not result.found)",
        "ensure s.capacity > 0 implies result.index < s.capacity",
        "ensure result.found implies (s.capacity > 0 and s.items != null)",
    ),
}
for name, required in contracts.items():
    section = compact(function_section(source, name))
    if any(compact(contract) not in section for contract in required):
        raise SystemExit(f"{name} lost its capacity, sentinel, or backing-storage postcondition")
    if "trustedUnsafe.AssumeProgress" in section:
        raise SystemExit(f"{name} still trusts its finite probe loop to make progress")

for name, required in {
    "arena_dict_find_index": (
        "while probed < m.capacity:",
        "decreases m.capacity - probed",
        "invariant probed <= m.capacity",
        "invariant slot < m.capacity",
        "invariant insert_slot == m.capacity or insert_slot < m.capacity",
    ),
    "arena_set_find_index": (
        "while probed < s.capacity:",
        "decreases s.capacity - probed",
        "invariant probed <= s.capacity",
        "invariant slot < s.capacity",
        "invariant insert_slot == s.capacity or insert_slot < s.capacity",
    ),
    "arena_dict_find_cstr_view_index": (
        "while remaining > 0:",
        "decreases remaining",
        "invariant remaining <= capacity",
        "invariant slot < capacity",
        "invariant insert_slot == capacity or insert_slot < capacity",
    ),
}.items():
    section = compact(function_section(source, name))
    if any(compact(fragment) not in section for fragment in required):
        raise SystemExit(f"{name} lost a finite-loop, slot-bound, or tombstone-candidate invariant")

positive_claims = {
    "dictionary_find_index_stays_within_positive_capacity": "probe.index < m.capacity",
    "set_find_index_stays_within_positive_capacity": "probe.index < s.capacity",
    "cstr_view_find_index_stays_within_positive_capacity": "probe.index < m.capacity",
    "dictionary_probe_match_requires_backing_storage": "not probe.found or m.items != null",
    "set_probe_match_requires_backing_storage": "not probe.found or s.items != null",
    "cstr_view_probe_match_requires_backing_storage": "not probe.found or m.items != null",
    "unavailable_dictionary_probe_uses_the_empty_sentinel": "probe.index == 0 and not probe.found",
    "unavailable_set_probe_uses_the_empty_sentinel": "probe.index == 0 and not probe.found",
    "unavailable_cstr_view_probe_uses_the_empty_sentinel": "probe.index == 0 and not probe.found",
}
positive_requires = {
    "dictionary_find_index_stays_within_positive_capacity": "requires m.capacity > 0",
    "set_find_index_stays_within_positive_capacity": "requires s.capacity > 0",
    "cstr_view_find_index_stays_within_positive_capacity": "requires m.capacity > 0",
    "unavailable_dictionary_probe_uses_the_empty_sentinel": "requires m.capacity == 0 or m.items == null",
    "unavailable_set_probe_uses_the_empty_sentinel": "requires s.capacity == 0 or s.items == null",
    "unavailable_cstr_view_probe_uses_the_empty_sentinel": "requires m.capacity == 0 or m.items == null",
}
negative_claims = {
    "a_dictionary_probe_can_escape_positive_capacity": "probe.index >= m.capacity",
    "a_set_probe_can_escape_positive_capacity": "probe.index >= s.capacity",
    "a_cstr_view_probe_can_escape_positive_capacity": "probe.index >= m.capacity",
    "a_probe_without_backing_storage_can_claim_a_match": "probe.found",
}
negative_requires = {
    "a_dictionary_probe_can_escape_positive_capacity": "requires m.capacity > 0",
    "a_set_probe_can_escape_positive_capacity": "requires s.capacity > 0",
    "a_cstr_view_probe_can_escape_positive_capacity": "requires m.capacity > 0",
    "a_probe_without_backing_storage_can_claim_a_match": "requires m.items == null",
}
bindings = {
    **{name: "arena_dict_find_index(m, key)" for name in (
        "dictionary_find_index_stays_within_positive_capacity",
        "dictionary_probe_match_requires_backing_storage",
        "unavailable_dictionary_probe_uses_the_empty_sentinel",
    )},
    **{name: "arena_set_find_index(s, key)" for name in (
        "set_find_index_stays_within_positive_capacity",
        "set_probe_match_requires_backing_storage",
        "unavailable_set_probe_uses_the_empty_sentinel",
    )},
    **{name: "arena_dict_find_cstr_view_index(m, key)" for name in (
        "cstr_view_find_index_stays_within_positive_capacity",
        "cstr_view_probe_match_requires_backing_storage",
        "unavailable_cstr_view_probe_uses_the_empty_sentinel",
    )},
    "a_dictionary_probe_can_escape_positive_capacity": "arena_dict_find_index(m, key)",
    "a_set_probe_can_escape_positive_capacity": "arena_set_find_index(s, key)",
    "a_cstr_view_probe_can_escape_positive_capacity": "arena_dict_find_cstr_view_index(m, key)",
    "a_probe_without_backing_storage_can_claim_a_match": "arena_dict_find_index(m, key)",
}
for path, claims, requirements, label in (
    (POSITIVE, positive_claims, positive_requires, "positive"),
    (NEGATIVE, negative_claims, negative_requires, "negative"),
):
    fixture = path.read_text()
    if declarations(fixture) != set(claims):
        raise SystemExit(f"{label} runtime probe theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in fixture \
            or 'include "../../elisacore_std/collections.elisa"' not in fixture:
        raise SystemExit(f"{label} runtime probe proofs no longer include the production collections")
    for name, claim in claims.items():
        section = compact(function_section(fixture, name))
        if compact("ensure result == true") not in section \
                or compact(claim) not in section \
                or (name in requirements and compact(requirements[name]) not in section) \
                or compact(bindings[name]) not in section:
            raise SystemExit(f"{label} runtime probe theorem {name} lost its claim, precondition, or source binding")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if COLLECTIONS not in source_closure:
    raise SystemExit("proof include closure no longer contains the production dictionary and set probes")
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_claims),
                      "false_claim_controls": len(negative_claims),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("runtime probe proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", COLLECTIONS, POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_claims)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == set(positive_claims)

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == set(negative_claims)
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not set(negative_claims) & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "dictionary, cstr-view dictionary, and set probes terminate with a result index in bounds for every positive capacity",
    "positive_claims_proved": sorted(positive_claims),
    "false_claims_refused": sorted(negative_claims),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
