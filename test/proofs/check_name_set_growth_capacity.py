"""Replay NameSet load-bound proofs against the production growth and insert paths."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
HELPER = ROOT / "src/semantic/name_set.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "name_set_growth_capacity.elisa"
NEGATIVE = HERE / "name_set_growth_capacity_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


def compact(text: str) -> str:
    return "".join(text.split())


helper_text = HELPER.read_text()
semantic_text = SEMANTIC.read_text()
if 'include "./name_set.elisa"' not in semantic_text:
    raise SystemExit("semantic pass no longer includes the NameSet implementation")

grow = compact(function_section(helper_text, "name_set_grow"))
expected_grow_fragments = (
    "capacity:mutableusize=16",
    "whilecapacity<(set.names.count+1)*2|capacity,set|:",
    "capacity<-capacity*2",
    "set.slots.truncate(0)",
    "set.slots.reserve(capacity)",
    "for slot_index in 0..<capacity|set|:",
    "set.slots.push(NAME_SET_SLOT_EMPTY)",
    "forrowin0..<set.names.count|set|:",
    "slot:usize=name_set_slot(set,set.names[row])",
    "set.slots[slot]<-row.u32()",
)
if any(compact(fragment) not in grow for fragment in expected_grow_fragments):
    raise SystemExit("NameSet growth no longer establishes the checked capacity threshold before rehash")

add = compact(function_section(helper_text, "name_set_add"))
expected_add_fragments = (
    "name_set_grow(set)ifset.slots.count<(set.names.count+1)*2",
    "slot:usize=name_set_slot(set,name)",
    "returnifset.slots[slot]!=NAME_SET_SLOT_EMPTY",
    "set.slots[slot]<-set.names.count.u32()",
    "set.names.push(name)",
)
if any(compact(fragment) not in add for fragment in expected_add_fragments):
    raise SystemExit("NameSet insertion no longer grows before a fresh insertion and preserves duplicate count")

slot = compact(function_section(helper_text, "name_set_slot"))
expected_slot_fragments = (
    "mask:usize=set.slots.count-1",
    "slot:mutableusize=name_hash(name).usize()&mask",
    "while set.slots[slot]!=NAME_SET_SLOT_EMPTY",
    "return slot if set.names[set.slots[slot].usize()]==name",
    "slot<-(slot+1)&mask",
)
if any(compact(fragment) not in slot for fragment in expected_slot_fragments):
    raise SystemExit("NameSet probing no longer follows the checked linear-probe path")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
positive_names = {
    "initial_capacity_covers_small_sets",
    "add_preserves_count_for_duplicate_name",
    "a_fresh_name_increments_the_count_once",
}
if not positive_names <= set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text)):
    raise SystemExit("NameSet capacity proof is missing a required theorem")
if "def exact_growth_threshold_leaves_an_extra_empty_slot(" not in negative_text:
    raise SystemExit("NameSet boundary counterexample is missing")
if "name_count <= 7" not in positive_text:
    raise SystemExit("initial-capacity theorem no longer covers the exact eight-entry range")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("NameSet capacity proof requires a strict proof build")

inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, Path(__file__), HELPER, SEMANTIC, POSITIVE, NEGATIVE]
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
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names <= verified
assert positive == run(POSITIVE)[1], "NameSet capacity proof changed across repeated runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "exact_growth_threshold_leaves_an_extra_empty_slot"),
]

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "initial NameSet capacity threshold for eight entries and insertion-count behavior",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claim_rejected": negative["findings"][0]["name"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
