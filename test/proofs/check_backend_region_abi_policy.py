"""Admit proofs for the backend's region-growth and explicit-allocator ABI policies."""
from __future__ import annotations

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
REGIONS = ROOT / "src/backend/codegen_abi_regions.elisa"
VARIANT_PATHS = ROOT / "src/backend/codegen_variant_paths.elisa"
REGION_FORWARDING = ROOT / "src/backend/codegen_region_forwarding.elisa"
DECLARE_SIGNATURE = ROOT / "src/backend/codegen_declare_signature.elisa"
PACKED_META = ROOT / "src/backend/codegen_packed_meta.elisa"
RUNTIME_STRINGS = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
POSITIVE = HERE / "backend_region_abi_policy.elisa"
NEGATIVE = HERE / "backend_region_abi_policy_rejected.elisa"

GROWTH_METHODS = {"push", "extend", "insert", "resize", "reserve", "put", "add", "append"}
POSITIVE_NAMES = {
    "region_growth_method_policy_is_exact",
    "no_named_mutator_means_no_region_growth",
    "appending_is_classified_as_region_growth",
    "explicit_allocator_helper_policy_is_exact",
    "dictionary_helpers_keep_their_explicit_allocator",
    "set_helpers_keep_their_explicit_allocator",
    "ordinary_helpers_do_not_keep_an_explicit_allocator",
}
NEGATIVE_NAMES = {
    "false_claim_read_only_method_grows",
    "false_claim_append_does_not_grow",
    "false_claim_ordinary_helper_has_explicit_allocator",
    "false_claim_dictionary_helper_lacks_explicit_allocator",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


regions_text = REGIONS.read_text()
growth_body = compact(function_section(regions_text, "region_growth_method"))
growth_literals = re.findall(r'method=="([^"\\]+)"', growth_body)
if set(growth_literals) != GROWTH_METHODS or len(growth_literals) != len(GROWTH_METHODS):
    raise SystemExit("region-growth classifier no longer has the exact, duplicate-free mutator set")
expected_growth_return = "return " + " or ".join(f'method == "{name}"' for name in (
    "push", "extend", "insert", "resize", "reserve", "put", "add", "append"))
if compact(expected_growth_return) not in growth_body:
    raise SystemExit("region-growth classifier changed its method policy")

allocator_body = compact(function_section(regions_text, "generic_helper_uses_explicit_allocator"))
expected_allocator_return = (
    'returnsview_matches_prefix(name,"arena_dict_",0,11)'
    'orsview_matches_prefix(name,"arena_set_",0,10)'
)
if expected_allocator_return not in allocator_body:
    raise SystemExit("explicit-allocator policy must be the exact dict/set helper prefix union")
if len("arena_dict_") != 11 or len("arena_set_") != 10:
    raise SystemExit("explicit-allocator prefix lengths changed")

prefix_body = compact(function_section(VARIANT_PATHS.read_text(), "sview_matches_prefix"))
prefix_steps = (
    'path_length:usize=path.len',
    'candidate_length:usize=candidate.len',
    'falsereturnifpath.len<0orcandidate.len<0',
    'falsereturnifpath_length.i64()!=path.lenorcandidate_length.i64()!=candidate.len',
    'falsereturnifstart<0orend<startorend>path.len',
    'falsereturnifend-start!=candidate.len',
    'matched:mutablebool=true',
    'forindexin0..<candidate_length|matched,path,candidate,start|',
    'matched<-falseifpath[(start+index.i64()).usize()]!=candidate[index]',
    'returnmatched',
)
prefix_positions = [prefix_body.find(step) for step in prefix_steps]
if any(position < 0 for position in prefix_positions) or prefix_positions != sorted(prefix_positions):
    raise SystemExit("explicit-allocator prefix comparison no longer checks each byte in order")

runtime_text = RUNTIME_STRINGS.read_text()
if {"sview_len", "sview_at"} & set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", runtime_text)):
    raise SystemExit("legacy sview length/index wrappers remain in the runtime")
index_body = compact(function_section(runtime_text, "string_view_index"))
index_steps = (
    '0returnifview.len<0',
    'view_len:usize=view.len.usize()',
    '0returnifview_len.i64()!=view.len',
    '0returnifindex<0orindex>=view.len',
    'returnview.data[index_usize].i64()',
)
index_positions = [index_body.find(step) for step in index_steps]
if any(position < 0 for position in index_positions) or index_positions != sorted(index_positions):
    raise SystemExit("prefix byte reads no longer reject out-of-range StringView indexes")

forwarding_body = compact(function_section(REGION_FORWARDING.read_text(), "region_scan_expression"))
if 'region_mark_root(region_growth_root(region_call_receiver),params,flags,structs)ifregion_growth_method(region_call_method)' not in forwarding_body:
    raise SystemExit("region-growth classification no longer guards receiver-region marking")
signature_text = compact(DECLARE_SIGNATURE.read_text())
if signature_text.count('signature_arena_slots<-0.usize()ifgeneric_helper_uses_explicit_allocator(function_name)') < 2:
    raise SystemExit("explicit-allocator classification no longer suppresses hidden signature arena slots")
packed_text = compact(PACKED_META.read_text())
if 'ifnotgeneric_helper_uses_explicit_allocator(base)' not in packed_text:
    raise SystemExit("packed generic helper metadata no longer uses the explicit-allocator classifier")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("region ABI proof inventory is incomplete or contains extras")
if 'include "./backend_region_abi_policy.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the positive region ABI proof")

growth_flags = [f"is_{name}" for name in ("push", "extend", "insert", "resize", "reserve", "put", "add", "append")]
growth_formula = " or ".join(growth_flags)
no_growth_precondition = " and ".join(f"not {flag}" for flag in growth_flags)
append_only_precondition = " and ".join(f"not {flag}" for flag in growth_flags[:-1]) + " and is_append"
growth_shapes = {
    "region_growth_method_policy_is_exact": f"ensure result == ({growth_formula}) return {growth_formula}",
    "no_named_mutator_means_no_region_growth": f"requires {no_growth_precondition} ensure result == false return {growth_formula}",
    "appending_is_classified_as_region_growth": f"requires {append_only_precondition} ensure result == true return {growth_formula}",
}
allocator_formula = "has_dict_prefix or has_set_prefix"
allocator_shapes = {
    "explicit_allocator_helper_policy_is_exact": f"ensure result == ({allocator_formula}) return {allocator_formula}",
    "dictionary_helpers_keep_their_explicit_allocator": f"requires has_dict_prefix and not has_set_prefix ensure result == true return {allocator_formula}",
    "set_helpers_keep_their_explicit_allocator": f"requires not has_dict_prefix and has_set_prefix ensure result == true return {allocator_formula}",
    "ordinary_helpers_do_not_keep_an_explicit_allocator": f"requires not has_dict_prefix and not has_set_prefix ensure result == false return {allocator_formula}",
}
positive_shapes = growth_shapes | allocator_shapes
negative_shapes = {
    "false_claim_read_only_method_grows": f"requires {no_growth_precondition} ensure result == true return {growth_formula}",
    "false_claim_append_does_not_grow": f"requires {append_only_precondition} ensure result == false return {growth_formula}",
    "false_claim_ordinary_helper_has_explicit_allocator": f"requires not has_dict_prefix and not has_set_prefix ensure result == true return {allocator_formula}",
    "false_claim_dictionary_helper_lacks_explicit_allocator": f"requires has_dict_prefix and not has_set_prefix ensure result == false return {allocator_formula}",
}
for path, expected_shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, shape in expected_shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states its intended region ABI policy")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("region ABI proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    REGIONS,
    VARIANT_PATHS,
    REGION_FORWARDING,
    DECLARE_SIGNATURE,
    PACKED_META,
    RUNTIME_STRINGS,
    POSITIVE,
    NEGATIVE,
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
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 14
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert negative["summary"]["obligations"] == 22 and negative["summary"]["proven"] == 18
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay or final provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "only receiver-mutating methods contribute inferred growth; arena_dict_/arena_set_ templates retain their explicit allocator ABI",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
