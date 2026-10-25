"""Admit exact-span ownership lookup laws with source-structure and replay checks."""
import hashlib
import json
import os
import argparse
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = ROOT.parent / "elisa-proof"
parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without proof-product replay")
ARGS = parser.parse_args()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
from proof_product_gate import require_current_product, source_include_closure

POSITIVE = HERE / "ownership_binding_lookup.elisa"
NEGATIVE = HERE / "ownership_binding_lookup_rejected.elisa"
TABLE_SOURCE = ROOT / "src/semantic/semantic_types_symbol_table.elisa"
POS_SOURCE = ROOT / "src/parser/parser_tokens.elisa"
LOOKUP_SOURCE = ROOT / "src/semantic/ownership_binding_lookup.elisa"
IDENTITY_SOURCE = ROOT / "src/semantic/binding_identity_types.elisa"
SENTINEL_SOURCE = ROOT / "src/semantic/symbols_hash_index.elisa"
REPRO = ROOT / "test/repro/typestate_binding_identity_probe.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
manifest = {}
binary_digest = ""
compiler_head = ""
if not ARGS.source_only:
    manifest = require_current_product(BIN, PROVER)
    binary_digest = hashlib.sha256(BIN.read_bytes()).hexdigest()
    compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   check=True, capture_output=True, text=True).stdout.strip()
    if manifest.get("compiler", {}).get("source_revision") != compiler_head:
        raise SystemExit("proof executable was built against a different compiler revision")


def struct_fields(path: Path, name: str) -> dict[str, str]:
    lines = path.read_text().splitlines()
    declaration = re.compile(rf"^( *)struct {re.escape(name)}:\s*$")
    for index, line in enumerate(lines):
        match = declaration.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        fields = {}
        for field_line in lines[index + 1:]:
            if not field_line.strip() or field_line.lstrip().startswith("#"):
                continue
            field_indent = len(field_line) - len(field_line.lstrip(" "))
            if field_indent <= indent:
                break
            if field_indent != indent + 4:
                continue
            field = re.match(r"^\s*([A-Za-z_]\w*):\s*(.*?)\s*$", field_line)
            if field:
                field_type = re.sub(r"\s*=\s*.*$", "", field.group(2)).strip()
                fields[field.group(1)] = re.sub(r"\s+", "", field_type)
        return fields
    raise AssertionError(f"struct {name} not found in {path}")


production_table = struct_fields(TABLE_SOURCE, "SymbolTable")
proof_table = struct_fields(POSITIVE, "SymbolTable")
projected_fields = {
    "symbols": "mutabledarray[Symbol]",
    "ref_pos": "mutabledarray[Ast::Pos]",
    "ref_binding_ids": "mutabledarray[BindingId]",
    "ref_owner_index_valid": "mutablebool",
    "ref_owner_next": "mutabledarray[u32]",
    "ref_owner_heads": "mutabledarray[u32]",
    "ref_owner_tails": "mutabledarray[u32]",
    "ref_owner_counts": "mutabledarray[u32]",
    "ref_owner_observed_counts": "mutabledarray[usize]",
}
for field, expected_type in projected_fields.items():
    if production_table.get(field) != expected_type:
        raise AssertionError(f"production SymbolTable.{field}: {production_table.get(field)!r}")
    if proof_table.get(field) != expected_type:
        raise AssertionError(f"proof projection SymbolTable.{field}: {proof_table.get(field)!r}")

expected_pos = {
    "line": "mutableu32", "column": "mutableu32", "offset": "mutableu32",
    "end_line": "mutableu32", "end_column": "mutableu32", "end_offset": "mutableu32",
}
if struct_fields(POS_SOURCE, "Pos") != expected_pos:
    raise AssertionError("production Ast::Pos layout changed; update the proof projection")
if struct_fields(POSITIVE, "Pos") != expected_pos:
    raise AssertionError("proof Ast::Pos projection differs from the production layout")

lookup_text = LOOKUP_SOURCE.read_text()
proof_text = POSITIVE.read_text()
repro_text = REPRO.read_text()
for required in (
    'include "../../src/semantic/ownership_binding_lookup.elisa"',
    'include "../../src/semantic/binding_identity_types.elisa"',
    'include "../../src/semantic/ownership_binding_flow.elisa"',
    'include "../../src/semantic/ownership_flow_domain.elisa"',
):
    if required not in proof_text:
        raise AssertionError(f"proof no longer includes production source: {required}")
if not re.search(r"table\.symbols\.count", lookup_text):
    raise AssertionError("lookup no longer validates the owner against the symbol count")
if re.search(r"table\.symbols\.(?!count\b)", lookup_text):
    raise AssertionError("opaque Symbol projection is no longer sufficient")

def constant_value(path: Path, name: str) -> int:
    match = re.search(rf"\bconst\s+{re.escape(name)}\s*:\s*u32\s*=\s*(\d+)", path.read_text())
    if not match:
        raise AssertionError(f"constant {name} not found in {path}")
    return int(match.group(1))


invalid_owner = constant_value(IDENTITY_SOURCE, "INVALID_DECL_ID_VALUE")
sentinel = constant_value(SENTINEL_SOURCE, "SYMBOL_INDEX_ROW_NONE")
if invalid_owner != sentinel:
    raise AssertionError("binding invalid-owner and symbol-index sentinels diverged")
if "const SYMBOL_INDEX_ROW_NONE: u32 = Semantic::INVALID_DECL_ID_VALUE" not in proof_text:
    raise AssertionError("proof sentinel projection no longer matches the production index")

# Concrete proofs and the runtime probe cover malformed/ambiguous shapes. The
# public API contract stays focused on witness soundness and miss sentinels.
for required in (
    "exact_lookup: Semantic::OwnershipBindingLookupResult = Semantic::ownership_binding_at_position(&table, recorded_id.owner, table.ref_pos[index])",
    "return 87 if not exact_lookup.known or exact_lookup.witness_index != index or not Semantic::ownership_binding_ids_equal(recorded_id, exact_lookup.binding_id)",
    "fallback_lookup: Semantic::OwnershipBindingLookupResult = Semantic::ownership_binding_at_position(&table, recorded_id.owner, table.ref_pos[index])",
    "return 91 if not fallback_lookup.known or fallback_lookup.witness_index != index or not Semantic::ownership_binding_ids_equal(exact_lookup.binding_id, fallback_lookup.binding_id)",
    "return 88 if line_only_lookup.known or line_only_lookup.binding_id.owner.value != 4294967295 or line_only_lookup.binding_id.serial != Semantic::FIRST_BINDING_SERIAL or line_only_lookup.witness_index != Semantic::INVALID_DECL_ID_VALUE.usize()",
    "ambiguous_lookup: Semantic::OwnershipBindingLookupResult = Semantic::ownership_binding_at_position(&table, outer.binding_id.owner, table.ref_pos[0])",
    "return 89 if ambiguous_lookup.known or ambiguous_lookup.binding_id.owner.value != 4294967295 or ambiguous_lookup.binding_id.serial != Semantic::FIRST_BINDING_SERIAL or ambiguous_lookup.witness_index != Semantic::INVALID_DECL_ID_VALUE.usize()",
    "misaligned_lookup: Semantic::OwnershipBindingLookupResult = Semantic::ownership_binding_at_position(&table, outer.binding_id.owner, table.ref_pos[0])",
    "return 90 if misaligned_lookup.known or misaligned_lookup.binding_id.owner.value != 4294967295 or misaligned_lookup.binding_id.serial != Semantic::FIRST_BINDING_SERIAL or misaligned_lookup.witness_index != Semantic::INVALID_DECL_ID_VALUE.usize()",
    "cyclic_lookup: Semantic::OwnershipBindingLookupResult = Semantic::ownership_binding_at_position(&table, outer.binding_id.owner, table.ref_pos[head])",
    "return 92 if cyclic_lookup.known or cyclic_lookup.binding_id.owner.value != 4294967295 or cyclic_lookup.binding_id.serial != Semantic::FIRST_BINDING_SERIAL or cyclic_lookup.witness_index != Semantic::INVALID_DECL_ID_VALUE.usize()",
):
    if required not in repro_text:
        raise AssertionError(f"ownership lookup regression case missing from concrete probe: {required}")

required_contracts = (
    "struct OwnershipBindingLookupResult:",
    "known: bool",
    "binding_id: BindingId",
    "witness_index: usize",
    "def ownership_binding_at_position(table: SymbolTable&, owner: DeclId, position: Ast::Pos) -> OwnershipBindingLookupResult",
    "ensure result.known implies result.binding_id.owner.value == owner.value",
    "ensure result.known implies owner.value != INVALID_DECL_ID_VALUE",
    "ensure result.known implies owner.value.usize() < table.symbols.count",
    "ensure result.known implies position.end_offset > position.offset",
    "ensure result.known implies table.ref_pos.count == table.ref_binding_ids.count",
    "ensure result.known implies not table.ref_owner_index_valid or table.ref_owner_next.count == table.ref_pos.count",
    "ensure result.known implies not table.ref_owner_index_valid or owner.value.usize() < table.ref_owner_heads.count",
    "ensure result.known implies result.witness_index < table.ref_pos.count",
    "ensure result.known implies result.witness_index < table.ref_binding_ids.count",
    "ensure result.known implies table.ref_binding_ids[result.witness_index].owner.value == owner.value",
    "ensure result.known implies table.ref_binding_ids[result.witness_index].owner.value == result.binding_id.owner.value",
    "ensure result.known implies table.ref_binding_ids[result.witness_index].serial == result.binding_id.serial",
    "ensure result.known implies table.ref_pos[result.witness_index].offset == position.offset",
    "ensure result.known implies table.ref_pos[result.witness_index].end_offset == position.end_offset",
    "ensure not result.known implies result.binding_id.owner.value == INVALID_DECL_ID_VALUE",
    "ensure not result.known implies result.binding_id.serial == FIRST_BINDING_SERIAL",
    "return OwnershipBindingLookupResult{known: false, binding_id: BindingId{owner: DeclId{value: INVALID_DECL_ID_VALUE}, serial: FIRST_BINDING_SERIAL}, witness_index: SYMBOL_INDEX_ROW_NONE.usize()} if:",
    "if not table.ref_owner_index_valid and owner.value != INVALID_DECL_ID_VALUE",
    "and table.ref_pos.count == 1 and table.ref_binding_ids.count == 1",
    "fallback_binding_id: BindingId = table.ref_binding_ids[0]",
    "assert ownership_lookup_candidate_matches(table, 0, owner, position, fallback_binding_id)",
    "return OwnershipBindingLookupResult{known: true, binding_id: fallback_binding_id, witness_index: 0}",
    "table.ref_owner_next[0] == 0",
    "singleton_head: usize = table.ref_owner_heads[owner.value.usize()].usize()",
    "table.ref_owner_next[singleton_head] == SYMBOL_INDEX_ROW_NONE",
    "duplicate_head: usize = table.ref_owner_heads[owner.value.usize()].usize()",
    "duplicate_second: usize = table.ref_owner_next[duplicate_head].usize()",
    "not ownership_binding_ids_equal(table.ref_binding_ids[duplicate_head], table.ref_binding_ids[duplicate_second])",
    "expected_count: usize = table.ref_owner_counts[owner.value.usize()].usize()",
    "lookup_valid: mutable bool = true",
    "if expected_count > table.ref_pos.count or expected_count != table.ref_owner_observed_counts[owner.value.usize()]",
    "row: mutable u32 = table.ref_owner_heads[owner.value.usize()]",
    "if row == SYMBOL_INDEX_ROW_NONE or row.usize() >= table.ref_pos.count or row.usize() >= table.ref_owner_next.count",
    "if id.owner.value != owner.value",
    "if row != SYMBOL_INDEX_ROW_NONE or last_row != expected_tail",
    "if not lookup_valid:",
    "for step in 0..<expected_count",
    "selected_binding_id: BindingId = table.ref_binding_ids[result_index]",
    "assert ownership_lookup_candidate_matches(table, result_index, owner, position, selected_binding_id)",
    "return OwnershipBindingLookupResult{known: true, binding_id: table.ref_binding_ids[result_index], witness_index: result_index}",
    "return OwnershipBindingLookupResult{known: true, binding_id: selected_binding_id, witness_index: result_index}",
)
normalized_lookup = re.sub(r"\s+", " ", lookup_text)
for contract in required_contracts:
    if re.sub(r"\s+", " ", contract) not in normalized_lookup:
        raise AssertionError(f"required source contract missing: {contract}")
if "return (" in lookup_text or "return OwnershipBindingLookupResult{" not in lookup_text:
    raise AssertionError("lookup must return the named result value, not a tuple or output refs")
miss_result = "return OwnershipBindingLookupResult{known: false, binding_id: BindingId{owner: DeclId{value: INVALID_DECL_ID_VALUE}, serial: FIRST_BINDING_SERIAL}, witness_index: SYMBOL_INDEX_ROW_NONE.usize()}"
if normalized_lookup.count(miss_result) != 5:
    raise AssertionError("all early/final miss returns must carry the canonical binding and witness sentinels")
if re.search(r"^\s*assert\s+exists\b", lookup_text, re.MULTILINE):
    raise AssertionError("runtime lookup path must not scan a quantified witness assertion")
if "exists candidate in 0..<table.ref_pos.count" in lookup_text or "exists candidate in 0..<table.ref_pos.count" in proof_text:
    raise AssertionError("selected-witness result should avoid a whole-table quantified lookup")
if "ownership_lookup_output_obeys_contract" in proof_text:
    raise AssertionError("proof fixture must not rely on an unused source-text-only helper")
if proof_text.count("lookup_result.witness_index == row") != 1:
    raise AssertionError("exact indexed-bucket proof must assert its selected witness row")
if proof_text.count("lookup_result.witness_index == 0") != 1:
    raise AssertionError("fallback proof must assert its selected witness row")
if proof_text.count("lookup_result.witness_index == Semantic::INVALID_DECL_ID_VALUE.usize()") != 9:
    raise AssertionError("each formal miss proof must assert the canonical witness sentinel")
lookup_lines = lookup_text.splitlines()
lookup_contract = lookup_text.split("def ownership_binding_at_position(", 1)[1].split("can Abort.Panic:", 1)[0]
lookup_contract_lines = lookup_contract.splitlines()
if sum(line.lstrip().startswith("ensure ") for line in lookup_contract_lines) != 16:
    raise AssertionError("ownership lookup core contract set changed; review this proof gate")
helper_contract = lookup_text.split("def ownership_lookup_candidate_matches(", 1)[1].split("public:", 1)[0]
if sum(line.lstrip().startswith("ensure ") for line in helper_contract.splitlines()) != 1:
    raise AssertionError("selected-row witness helper contract changed; review this proof gate")
if sum(line.lstrip().startswith("invariant ") for line in lookup_lines) != 4:
    raise AssertionError("ownership lookup loop invariant set changed; review this proof gate")
if sum(line.lstrip().startswith("decreases ") for line in lookup_lines) != 0:
    raise AssertionError("ownership lookup should use bounded for loops; review this proof gate")

if ARGS.source_only:
    print(json.dumps({"source_bound": True, "contract_count": 16,
                      "invariant_count": 4,
                      "scope": "named-result exact witness contract with concrete fail-closed regression cases"}, sort_keys=True))
    raise SystemExit(0)

SOURCES = [Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE, TABLE_SOURCE, POS_SOURCE,
           LOOKUP_SOURCE, IDENTITY_SOURCE, SENTINEL_SOURCE, REPRO,
           ROOT / "src/semantic/ownership_flow_domain.elisa",
           ROOT / "src/semantic/ownership_binding_flow.elisa"]
compiler_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(compiler_product) + ".provenance.json")
INPUTS = [*source_include_closure([POSITIVE, NEGATIVE]), BIN, MANIFEST, MANIFEST_CHECKSUM, (PROVER / "ELISA_COMPILER_REV").resolve(strict=True),
          Path(manifest["compiler"]["executable"]["path"]).resolve(strict=True), compiler_product,
          Path(manifest["runtime"]["path"]).resolve(strict=True),
          Path(manifest["profile_hooks"]["path"]).resolve(strict=True),
          stage1_provenance, *SOURCES]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}


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
expected_positive = {
    "ownership_binding_at_position",
    "exact_reference_at_owner_bucket_head_is_found",
    "fallback_scan_finds_single_exact_reference", "conflicting_exact_rows_obey_lookup_contract",
    "matching_row_in_a_malformed_self_loop_obeys_lookup_contract",
    "a_different_span_is_rejected",
    "zero_width_span_is_rejected", "invalid_owner_is_rejected",
    "out_of_range_owner_is_rejected",
    "misaligned_reference_arrays_are_rejected", "stale_index_links_are_rejected",
    "missing_owner_bucket_is_rejected",
}
assert expected_positive <= verified
assert all(row.get("verified") for row in positive["declaration_details"] if row["kind"] == "function")

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
negative_claims = {"zero_width_span_is_known", "unrecorded_span_is_known"}
assert negative["summary"]["proven"] + len(negative_claims) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_claims
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_claims & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert all(row.get("verified") for row in negative["declaration_details"]
           if row["kind"] == "function" and row["name"] not in negative_claims)

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert hashes_before == hashes_after, "proof inputs changed during replay"
assert require_current_product(BIN, PROVER) == manifest, "proof product or source tree changed during replay"
assert subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                      check=True, capture_output=True, text=True).stdout.strip() == compiler_head
print(json.dumps({"admitted": True,
                  "scope": "narrow exact-span contract, singleton proof cases, and source-bound malformed/ambiguous regression cases",
                  "positive_obligations": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": sorted(negative_claims),
                  "proof_binary_sha256": binary_digest,
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
