"""Bind region-analysis scratch-slot isolation and restoration to backend source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=not args.source_only)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
ABI_REGIONS = ROOT / "src/backend/codegen_abi_regions.elisa"
REGION_FORWARDING = ROOT / "src/backend/codegen_region_forwarding/root_scan.elisa"
POSITIVE = HERE / "backend_region_alias_scratch.elisa"
NEGATIVE = HERE / "backend_region_alias_scratch_rejected.elisa"
POSITIVE_NAMES = {
    "fallback_graph_slot_is_disjoint_from_every_fact",
    "fallback_restores_the_previous_graph_slot",
}
NEGATIVE_NAMES = {
    "false_fallback_scratch_reuses_a_fact_slot",
    "false_fallback_changes_the_previous_graph_slot",
}
PROOF_HASHES = {
    "fallback_graph_slot_is_disjoint_from_every_fact": "0ef0736f5035bf31ed8e35e4ab4e3f86afc21ba93e70a5b65af7cef5c281f551",
    "fallback_restores_the_previous_graph_slot": "a889b5992a06af9c8954b9ec8f39852f03ab4c3c19ca7f29142bf2f1906b50f4",
    "false_fallback_scratch_reuses_a_fact_slot": "a82cfecdcb360a9e631396eac2f1bf78f70a283510a222c774b1195320e25f73",
    "false_fallback_changes_the_previous_graph_slot": "a48a0e46e024cb26b1d6ee525f7b52150f0685fbc4ae8a5b71b92d494c90c7ed",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one {name} declaration")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


abi = ABI_REGIONS.read_text()
forwarding = REGION_FORWARDING.read_text()
fallback = compact(section(abi, "region_flags_for_function"))
for shape in (
    "scratch_graph_slot:usize=structs.regions.region_fact_names.count",
    "previous_graph_slot:usize=structs.regions.region_alias_graph_active_slot",
    "body_region_parameter_flags(params,body,scratch_graph_slot,structs,flags)",
    "structs.regions.region_alias_graph_active_slot<-previous_graph_slot",
):
    if shape not in fallback:
        raise SystemExit(f"region fallback lost scratch-slot isolation/restoration: {shape}")
if "body_region_parameter_flags(params,body,structs,flags)" in fallback:
    raise SystemExit("region fallback reintroduced same-argument self recursion")
body_scan = compact(section(forwarding, "body_region_parameter_flags"))
for shape in (
    "defbody_region_parameter_flags(params:darray[ParamDecl]&,body:darray[Stmt],graph_slot:usize",
    "region_alias_graph_ensure_slot(graph_slot,structs)",
    "structs.regions.region_alias_graph_active_slot<-graph_slot",
):
    if shape not in body_scan:
        raise SystemExit(f"body region scan no longer uses its explicit graph slot: {shape}")
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("region alias scratch proof inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_region_alias_scratch.elisa"'):
    raise SystemExit("region alias false claims must include the positive policy model")
for name, expected in PROOF_HASHES.items():
    owner = POSITIVE if name in POSITIVE_NAMES else NEGATIVE
    actual = hashlib.sha256(compact(section(owner.read_text(), name)).encode()).hexdigest()
    if actual != expected:
        raise SystemExit(f"region scratch theorem {name} changed since source binding")

if args.source_only:
    print(json.dumps({"source_bound": True, "positive": len(POSITIVE_NAMES),
                      "false_controls": len(NEGATIVE_NAMES)}))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("region alias scratch proof requires a strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV",
    Path(__file__), HERE / "proof_product_gate.py", ABI_REGIONS, REGION_FORWARDING,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=60)
    return process.returncode, json.loads(process.stdout)


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES
code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("compiler or proof inputs changed during replay")
print(json.dumps({"positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": sorted(NEGATIVE_NAMES), "source_bound": True}))
