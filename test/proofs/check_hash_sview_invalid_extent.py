"""Bind invalid-extent FNV claims to the hash helper's early returns."""
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
RUNTIME = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
HASH_RUNTIME = ROOT / "elisacore_std/elisacore_runtime_string_hash.elisa"
FNV_SPEC = ROOT / "elisacore_std/elisacore_fnv1a_spec.elisa"
COLLECTIONS = ROOT / "elisacore_std/collections.elisa"
POSITIVE = HERE / "hash_sview_invalid_extent.elisa"
NEGATIVE = HERE / "hash_sview_invalid_extent_rejected.elisa"
INITIAL_STATE = "0xcbf29ce484222325"
INITIAL_STATE_NAME = "SVIEW_FNV1A_OFFSET_BASIS"
PRIME_NAME = "SVIEW_FNV1A_PRIME"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(
        rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


runtime_text = RUNTIME.read_text()
hash_text = HASH_RUNTIME.read_text()
spec_text = FNV_SPEC.read_text()
collections_text = COLLECTIONS.read_text()
hash_body = compact(function_section(hash_text, "hash_sview"))
contract = (
    f"ensure (value.len <= 0 or value.len.usize().i64() != value.len) "
    f"implies result == {INITIAL_STATE_NAME}"
)
if compact(contract) not in hash_body:
    raise SystemExit("hash_sview lost its invalid-extent seed postcondition")

if f"const{INITIAL_STATE_NAME}:u64={INITIAL_STATE}" not in compact(spec_text) or \
        f"const{PRIME_NAME}:u64=0x100000001b3" not in compact(spec_text):
    raise SystemExit("StringView FNV constants changed without updating the byte-fold specification")
if compact('include "./elisacore_runtime_string_hash.elisa"') not in compact(runtime_text):
    raise SystemExit("runtime strings no longer imports the specified StringView hash implementation")
if compact('include "./elisacore_fnv1a_spec.elisa"') not in compact(hash_text):
    raise SystemExit("StringView hash implementation lost its direct dependency on the shared FNV specification")
fold_spec = compact(function_section(spec_text, "sview_fnv1a_fold_from"))
if "requiresvalue.len>0andvalue.len.usize().i64()==value.len" not in fold_spec or \
        "requiresindex<=value.len.usize()" not in fold_spec or \
        "decreasesvalue.len.usize()-index" not in fold_spec or \
        f"(state^value[index].u8().u64())*{PRIME_NAME}" not in fold_spec:
    raise SystemExit("recursive FNV specification lost its bounded index, termination measure, or update step")
model_spec = compact(function_section(spec_text, "sview_fnv1a_model"))
if compact("ensure result == sview_fnv1a_model(value)") not in hash_body or \
        "returnSVIEW_FNV1A_OFFSET_BASISifvalue.len<=0orvalue.len.usize().i64()!=value.len" not in model_spec or \
        f"return sview_fnv1a_fold_from(value, 0.usize(), {INITIAL_STATE_NAME})".replace(" ", "") not in model_spec:
    raise SystemExit("hash_sview or the shared all-extents FNV model lost its valid/invalid result contract")

required_steps = (
    f"h: mutable u64 = {INITIAL_STATE_NAME}",
    "return h if value.len <= 0",
    "view_len: usize = value.len.usize()",
    "return h if view_len.i64() != value.len",
    "i: mutable usize = 0",
    "while i < view_len:",
    "decreases view_len - i",
    "invariant i <= view_len",
    "invariant i.i64().usize() == i",
    "invariant view_len == value.len",
    f"invariant sview_fnv1a_fold_from(value, i, h) == sview_fnv1a_fold_from(value, 0.usize(), {INITIAL_STATE_NAME})",
    "ch: u8 = value[i].u8()",
    "h <- h ^ ch.u64()",
    f"h <- h * {PRIME_NAME}",
    "i <- i + 1.usize()",
)
step_positions = [hash_body.find(compact(step)) for step in required_steps]
if any(position < 0 for position in step_positions) or step_positions != sorted(step_positions):
    raise SystemExit("hash_sview no longer rejects invalid lengths before initializing its scan")
if hash_body.rfind(compact("return h")) < step_positions[-1]:
    raise SystemExit("hash_sview no longer returns the accumulated FNV state after its byte scan")
if "canUnsafe.UncheckedIndex" in hash_body or hash_body.count("value[i].u8()") != 1 \
        or "string_view_index(value," in hash_body or "sview_at(value," in hash_body:
    raise SystemExit("hash_sview no longer uses the guarded StringView index syntax for each bounded byte")

collection_hash_body = compact(function_section(collections_text, "ctx_hash_sview"))
collection_required_steps = (
    "ensure result == sview_fnv1a_model(view)",
    "h: mutable u64 = SVIEW_FNV1A_OFFSET_BASIS",
    "return h if view.len <= 0",
    "view_len: usize = view.len.usize()",
    "return h if view_len.i64() != view.len",
    "i: mutable usize = 0",
    "while i < view_len:",
    "decreases view_len - i",
    "invariant i <= view_len",
    "invariant i.i64().usize() == i",
    "invariant view_len.i64() == view.len",
    f"invariant sview_fnv1a_fold_from(view, i, h) == sview_fnv1a_fold_from(view, 0.usize(), {INITIAL_STATE_NAME})",
    f"h <- (h ^ view[i].u8().u64()) * {PRIME_NAME}",
    "i <- i + 1.usize()",
    "return h",
)
collection_positions = [collection_hash_body.find(compact(step)) for step in collection_required_steps]
collection_positions[-1] = collection_hash_body.rfind(compact(collection_required_steps[-1]))
if any(position < 0 for position in collection_positions) or collection_positions != sorted(collection_positions):
    raise SystemExit("ctx_hash_sview lost its shared model contract or bounded FNV loop")
if "canUnsafe.UncheckedIndex" in collection_hash_body or "view.data[i]" in collection_hash_body:
    raise SystemExit("ctx_hash_sview reintroduced an unchecked raw-pointer read")

positive_names = {
    "every_rejected_hash_extent_returns_the_initial_fnv_state",
    "a_nonpositive_hash_extent_returns_the_initial_fnv_state",
    "every_view_hash_matches_the_recursive_fnv1a_fold",
    "collection_and_runtime_view_hashes_agree",
    "an_empty_view_hash_is_the_fnv1a_offset_basis",
    "a_one_byte_view_hash_applies_one_fnv1a_step",
    "a_two_byte_view_hash_preserves_byte_order",
}
negative_names = {
    "an_invalid_hash_extent_can_change_the_fnv_seed",
    "a_nonpositive_hash_extent_can_change_the_fnv_seed",
    "a_valid_empty_view_hash_can_be_zero",
    "a_nonempty_view_hash_can_return_the_offset_basis",
    "collection_and_runtime_hashes_can_disagree",
}
claims = {
    "every_rejected_hash_extent_returns_the_initial_fnv_state": f"hash_sview(view) == {INITIAL_STATE}",
    "a_nonpositive_hash_extent_returns_the_initial_fnv_state": f"hash_sview(view) == {INITIAL_STATE}",
    "every_view_hash_matches_the_recursive_fnv1a_fold": "hash_sview(view) == sview_fnv1a_model(view)",
    "collection_and_runtime_view_hashes_agree": "ctx_hash_sview(view) == hash_sview(view)",
    "an_empty_view_hash_is_the_fnv1a_offset_basis": f"hash_sview(view) == {INITIAL_STATE_NAME}",
    "a_one_byte_view_hash_applies_one_fnv1a_step": f"hash_sview(view) == ({INITIAL_STATE_NAME} ^ byte) * {PRIME_NAME}",
    "a_two_byte_view_hash_preserves_byte_order": "hash_sview(view) == expected",
    "an_invalid_hash_extent_can_change_the_fnv_seed": f"hash_sview(view) != {INITIAL_STATE}",
    "a_nonpositive_hash_extent_can_change_the_fnv_seed": f"hash_sview(view) != {INITIAL_STATE}",
    "a_valid_empty_view_hash_can_be_zero": "hash_sview(view) == 0",
    "a_nonempty_view_hash_can_return_the_offset_basis": f"hash_sview(view) == {INITIAL_STATE_NAME}",
    "collection_and_runtime_hashes_can_disagree": "ctx_hash_sview(view) != hash_sview(view)",
}
requirements = {
    "every_rejected_hash_extent_returns_the_initial_fnv_state": f"requires view.len <= 0 or view.len.usize().i64() != view.len",
    "a_nonpositive_hash_extent_returns_the_initial_fnv_state": "requires view.len <= 0",
    "every_view_hash_matches_the_recursive_fnv1a_fold": "",
    "collection_and_runtime_view_hashes_agree": "",
    "an_empty_view_hash_is_the_fnv1a_offset_basis": "requires view.len == 0",
    "a_one_byte_view_hash_applies_one_fnv1a_step": "requires view.length == 1 and view.length.usize().i64() == view.length",
    "a_two_byte_view_hash_preserves_byte_order": "requires view.length == 2 and view.length.usize().i64() == view.length",
    "an_invalid_hash_extent_can_change_the_fnv_seed": f"requires view.len <= 0 or view.len.usize().i64() != view.len",
    "a_nonpositive_hash_extent_can_change_the_fnv_seed": "requires view.len <= 0",
    "a_valid_empty_view_hash_can_be_zero": "requires view.len == 0",
    "a_nonempty_view_hash_can_return_the_offset_basis": "requires view.len > 0 and view.len.usize().i64() == view.len",
    "collection_and_runtime_hashes_can_disagree": "",
}
for source_text, names, label in (
    (POSITIVE.read_text(), positive_names, "positive"),
    (NEGATIVE.read_text(), negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} invalid-hash theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text \
            or 'include "../../elisacore_std/collections.elisa"' not in source_text:
        raise SystemExit(f"{label} invalid-hash theorem no longer includes the production runtime")
    for name in names:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section \
                or (requirements[name] and compact(requirements[name]) not in section) \
                or compact(claims[name]) not in section:
            raise SystemExit(f"{label} hash theorem {name} lost its claim or precondition")
        if "hash_sview(view)" not in section:
            raise SystemExit(f"{label} hash theorem {name} is no longer bound to hash_sview")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if HASH_RUNTIME not in source_closure or FNV_SPEC not in source_closure or COLLECTIONS not in source_closure:
    raise SystemExit("proof include closure no longer contains the production FNV implementation and shared specification")
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("invalid StringView hash proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", RUNTIME, HASH_RUNTIME, FNV_SPEC, COLLECTIONS,
    POSITIVE, NEGATIVE, *source_closure,
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "hash_sview refines a recursive byte-by-byte FNV-1a fold, preserves byte order, and returns the offset basis for invalid or empty extents",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
