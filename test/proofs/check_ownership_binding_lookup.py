"""Admit exact-span ownership lookup laws with source-structure and replay checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = ROOT.parent / "elisa-proof"
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
from proof_product_gate import require_current_product

POSITIVE = HERE / "ownership_binding_lookup.elisa"
NEGATIVE = HERE / "ownership_binding_lookup_rejected.elisa"
TABLE_SOURCE = ROOT / "src/semantic/semantic_types.elisa"
POS_SOURCE = ROOT / "src/parser/parser_tokens.elisa"
LOOKUP_SOURCE = ROOT / "src/semantic/ownership_binding_lookup.elisa"
IDENTITY_SOURCE = ROOT / "src/semantic/binding_identity_types.elisa"
SENTINEL_SOURCE = ROOT / "src/semantic/symbols_hash_index.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
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

required_contracts = (
    "result.known implies result.binding_id.owner.value == owner.value",
    "result.known implies owner.value != INVALID_DECL_ID_VALUE",
    "result.known implies owner.value.usize() < table.symbols.count",
    "result.known implies position.end_offset > position.offset",
    "result.known implies table.ref_pos.count == table.ref_binding_ids.count",
    "result.known implies not table.ref_owner_index_valid or table.ref_owner_next.count == table.ref_pos.count",
    "result.known implies not table.ref_owner_index_valid or owner.value.usize() < table.ref_owner_heads.count",
    "result.known implies exists candidate in 0..<table.ref_pos.count:",
    "not result.known implies result.binding_id.owner.value == INVALID_DECL_ID_VALUE",
    "not result.known implies result.binding_id.serial == FIRST_BINDING_SERIAL",
    "table.ref_owner_heads[owner.value.usize()].usize() != SYMBOL_INDEX_ROW_NONE.usize()",
    "not table.ref_owner_index_valid and owner.value != INVALID_DECL_ID_VALUE",
    "and (table.ref_pos[table.ref_owner_heads[owner.value.usize()].usize()].offset != position.offset or table.ref_pos[table.ref_owner_heads[owner.value.usize()].usize()].end_offset != position.end_offset)) implies not result.known",
    "and not ownership_binding_ids_equal(table.ref_binding_ids[table.ref_owner_heads[owner.value.usize()].usize()], table.ref_binding_ids[table.ref_owner_next[table.ref_owner_heads[owner.value.usize()].usize()].usize()])) implies not result.known",
    "table.ref_owner_heads[owner.value.usize()] == 0 and table.ref_owner_next[0] == 0 and table.ref_binding_ids[0].owner.value == owner.value",
    "invariant steps <= table.ref_pos.count",
    "decreases table.ref_pos.count - steps",
)
normalized_lookup = re.sub(r"\s+", " ", lookup_text)
for contract in required_contracts:
    if contract not in normalized_lookup:
        raise AssertionError(f"required source contract missing: {contract}")
lookup_lines = lookup_text.splitlines()
if sum(line.lstrip().startswith("ensure ") for line in lookup_lines) != 15:
    raise AssertionError("ownership lookup contract set changed; review and update this proof gate")
if sum(line.lstrip().startswith("invariant ") for line in lookup_lines) != 4:
    raise AssertionError("ownership lookup loop invariant set changed; review this proof gate")
if sum(line.lstrip().startswith("decreases ") for line in lookup_lines) != 1:
    raise AssertionError("ownership lookup termination measure changed; review this proof gate")

SOURCES = [Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE, TABLE_SOURCE, POS_SOURCE,
           LOOKUP_SOURCE, IDENTITY_SOURCE, SENTINEL_SOURCE,
           ROOT / "src/semantic/ownership_flow_domain.elisa",
           ROOT / "src/semantic/ownership_binding_flow.elisa"]
compiler_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(compiler_product) + ".provenance.json")
INPUTS = [BIN, MANIFEST, MANIFEST_CHECKSUM, (PROVER / "ELISA_COMPILER_REV").resolve(strict=True),
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
    "ownership_binding_at_position", "exact_reference_at_owner_bucket_head_is_found",
    "fallback_scan_finds_single_exact_reference", "conflicting_exact_rows_are_rejected",
    "matching_row_in_a_malformed_self_loop_is_rejected",
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
negative_claims = {"zero_width_span_is_known", "malformed_matching_self_loop_is_known"}
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
                  "scope": "exact-span soundness, singleton success, conflicting-row rejection, and fail-closed table paths",
                  "positive_obligations": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": sorted(negative_claims),
                  "proof_binary_sha256": binary_digest,
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
