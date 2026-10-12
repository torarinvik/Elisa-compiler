"""Source-bind and replay the backend caller-region slot policy proofs."""
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
POSITIVE = HERE / "backend_caller_region_policy.elisa"
NEGATIVE = HERE / "backend_caller_region_policy_rejected.elisa"

POSITIVE_NAMES = {
    "reference_growth_policy_is_exact",
    "referenced_values_carry_the_caller_region_when_needed",
    "returned_values_keep_their_owned_or_ast_region",
    "a_read_only_nonreference_does_not_add_a_caller_region",
    "a_dynamic_array_reference_carries_its_region",
    "returned_caller_owned_storage_keeps_its_region",
    "an_ast_arena_return_keeps_its_region",
    "signature_arena_requirement_is_exact",
    "an_explicit_allocator_suppresses_a_second_hidden_slot",
    "an_owned_return_uses_a_hidden_slot_without_an_explicit_allocator",
}
NEGATIVE_NAMES = {
    "false_claim_nonreference_type_grows",
    "false_claim_plain_reference_needs_caller_region",
    "false_claim_caller_owned_return_does_not_keep_its_region",
    "false_claim_plain_return_keeps_a_caller_region",
    "false_claim_explicit_allocator_adds_a_second_hidden_slot",
}

if not __debug__:
    raise SystemExit("run without Python -O")


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
production_shapes = {
    "ref_type_can_grow": """
def ref_type_can_grow(value_type: ValueType, structs: mutable StructTable&) -> bool can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast]:
    can Abort.Panic, Memory.Allocate, Unsafe.PointerCast:
        false return if value_type.kind != TypeKind.Ref
        target: ValueType = ref_target_of(value_type, structs)
        true return if target.kind == TypeKind.DArray
        true return if is_growable_container_struct(target, structs)
        true return if target.kind == TypeKind.Struct and struct_contains_darray(target, structs)
        return false
""",
    "value_type_carries_caller_region": """
def value_type_carries_caller_region(value_type: ValueType, structs: mutable StructTable&) -> bool can[Abort.Panic]:
    can Abort.Panic:
        false return if value_type.kind != TypeKind.Ref
        target: ValueType = ref_target_of(value_type, structs)
        true return if target.kind == TypeKind.DArray
        true return if is_growable_container_struct(target, structs)
        true return if target.kind == TypeKind.Struct and struct_contains_darray(target, structs)
        return ast_value_needs_arena(target, structs)
""",
    "value_type_returns_caller_region": """
def value_type_returns_caller_region(value_type: ValueType, structs: mutable StructTable&) -> bool can[Abort.Panic]:
    true return if value_type_owns_region_storage(value_type, structs, 0)
    return ast_value_needs_arena(value_type, structs)
""",
    "signature_needs_arena": """
def signature_needs_arena(params: darray[ParamDecl]&, return_value_type: ValueType, structs: mutable StructTable&) -> bool can[Abort.Panic]:
    can Abort.Panic, Memory.Allocate, Unsafe.PointerCast:
        false return if params_manage_arena(params, structs)
        return value_type_returns_caller_region(return_value_type, structs)
""",
}
for name, expected in production_shapes.items():
    if compact(function_section(regions_text, name)) != compact(expected):
        raise SystemExit(f"production caller-region classifier {name} changed without updating its proof binding")


proof_shapes = {
    "reference_growth_policy_is_exact": """
def reference_growth_policy_is_exact(is_reference: bool, target_is_darray: bool, target_is_growable_container: bool, target_is_struct: bool, struct_contains_darray: bool) -> bool:
    ensure result == (is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray)))
    return is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray))
""",
    "referenced_values_carry_the_caller_region_when_needed": """
def referenced_values_carry_the_caller_region_when_needed(is_reference: bool, target_is_darray: bool, target_is_growable_container: bool, target_is_struct: bool, struct_contains_darray: bool, ast_value_needs_arena: bool) -> bool:
    ensure result == (is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray) or ast_value_needs_arena))
    return is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray) or ast_value_needs_arena)
""",
    "returned_values_keep_their_owned_or_ast_region": """
def returned_values_keep_their_owned_or_ast_region(owns_region_storage: bool, ast_value_needs_arena: bool) -> bool:
    ensure result == (owns_region_storage or ast_value_needs_arena)
    return owns_region_storage or ast_value_needs_arena
""",
    "a_read_only_nonreference_does_not_add_a_caller_region": """
def a_read_only_nonreference_does_not_add_a_caller_region(is_reference: bool, target_is_darray: bool, target_is_growable_container: bool, target_is_struct: bool, struct_contains_darray: bool, ast_value_needs_arena: bool) -> bool:
    requires not is_reference
    ensure result == false
    return is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray) or ast_value_needs_arena)
""",
    "a_dynamic_array_reference_carries_its_region": """
def a_dynamic_array_reference_carries_its_region(is_reference: bool, target_is_darray: bool, target_is_growable_container: bool, target_is_struct: bool, struct_contains_darray: bool, ast_value_needs_arena: bool) -> bool:
    requires is_reference and target_is_darray
    ensure result == true
    return is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray) or ast_value_needs_arena)
""",
    "returned_caller_owned_storage_keeps_its_region": """
def returned_caller_owned_storage_keeps_its_region(owns_region_storage: bool, ast_value_needs_arena: bool) -> bool:
    requires owns_region_storage
    ensure result == true
    return owns_region_storage or ast_value_needs_arena
""",
    "an_ast_arena_return_keeps_its_region": """
def an_ast_arena_return_keeps_its_region(owns_region_storage: bool, ast_value_needs_arena: bool) -> bool:
    requires not owns_region_storage and ast_value_needs_arena
    ensure result == true
    return owns_region_storage or ast_value_needs_arena
""",
    "signature_arena_requirement_is_exact": """
def signature_arena_requirement_is_exact(params_manage_arena: bool, return_type_carries_caller_region: bool) -> bool:
    ensure result == (not params_manage_arena and return_type_carries_caller_region)
    return not params_manage_arena and return_type_carries_caller_region
""",
    "an_explicit_allocator_suppresses_a_second_hidden_slot": """
def an_explicit_allocator_suppresses_a_second_hidden_slot(params_manage_arena: bool, return_type_carries_caller_region: bool) -> bool:
    requires params_manage_arena
    ensure result == false
    return not params_manage_arena and return_type_carries_caller_region
""",
    "an_owned_return_uses_a_hidden_slot_without_an_explicit_allocator": """
def an_owned_return_uses_a_hidden_slot_without_an_explicit_allocator(params_manage_arena: bool, return_type_carries_caller_region: bool) -> bool:
    requires not params_manage_arena and return_type_carries_caller_region
    ensure result == true
    return not params_manage_arena and return_type_carries_caller_region
""",
}
negative_shapes = {
    "false_claim_nonreference_type_grows": """
def false_claim_nonreference_type_grows(is_reference: bool, target_is_darray: bool, target_is_growable_container: bool, target_is_struct: bool, struct_contains_darray: bool, ast_value_needs_arena: bool) -> bool:
    requires not is_reference
    ensure result == true
    return is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray) or ast_value_needs_arena)
""",
    "false_claim_plain_reference_needs_caller_region": """
def false_claim_plain_reference_needs_caller_region(is_reference: bool, target_is_darray: bool, target_is_growable_container: bool, target_is_struct: bool, struct_contains_darray: bool, ast_value_needs_arena: bool) -> bool:
    requires is_reference and not target_is_darray and not target_is_growable_container and not target_is_struct and not ast_value_needs_arena
    ensure result == true
    return is_reference and (target_is_darray or target_is_growable_container or (target_is_struct and struct_contains_darray) or ast_value_needs_arena)
""",
    "false_claim_caller_owned_return_does_not_keep_its_region": """
def false_claim_caller_owned_return_does_not_keep_its_region(owns_region_storage: bool, ast_value_needs_arena: bool) -> bool:
    requires owns_region_storage
    ensure result == false
    return owns_region_storage or ast_value_needs_arena
""",
    "false_claim_plain_return_keeps_a_caller_region": """
def false_claim_plain_return_keeps_a_caller_region(owns_region_storage: bool, ast_value_needs_arena: bool) -> bool:
    requires not owns_region_storage and not ast_value_needs_arena
    ensure result == true
    return owns_region_storage or ast_value_needs_arena
""",
    "false_claim_explicit_allocator_adds_a_second_hidden_slot": """
def false_claim_explicit_allocator_adds_a_second_hidden_slot(params_manage_arena: bool, return_type_carries_caller_region: bool) -> bool:
    requires params_manage_arena and return_type_carries_caller_region
    ensure result == true
    return not params_manage_arena and return_type_carries_caller_region
""",
}
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("caller-region proof inventory is incomplete or contains unexpected declarations")
for path, shapes in ((POSITIVE, proof_shapes), (NEGATIVE, negative_shapes)):
    text = path.read_text()
    for name, expected in shapes.items():
        if compact(function_section(text, name)) != compact(expected):
            raise SystemExit(f"{name} no longer proves the source-bound caller-region policy formula")
if 'include "./backend_caller_region_policy.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the positive caller-region proofs")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("caller-region policy proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
manifest = BIN.with_name(BIN.name + ".manifest.json")
inputs = list(dict.fromkeys([
    BIN, manifest, manifest.with_name(manifest.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", REGIONS, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
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
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 20
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES
assert positive == replay(POSITIVE)[1], "caller-region proof report changed across identical runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert negative["summary"]["obligations"] == 30 and negative["summary"]["proven"] == 25
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])

assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "caller-region proof inputs changed during replay or provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "ref growth, caller-region reference and return selection, and explicit-arena slot suppression",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
