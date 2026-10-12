"""Admit exact EASM contract-word proofs against a strict Elisa-proof product."""
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
POSITIVE = HERE / "easm_contract_membership.elisa"
NEGATIVE = HERE / "easm_contract_membership_rejected.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate production function {name}")
    return match.group(1)


provenance = PROVENANCE.read_text()
if compact(function_body(provenance, "easm_contract_has_word")) != compact(
    "return easm_contract_has_exact(values, needle)"
):
    raise SystemExit("contract-word queries no longer delegate to exact token membership")
expected_register_matcher = """
return true if easm_contract_has_exact(values, register)
for value in values:
    equals: usize = easm_find(value, "=")
    if equals < sview_len(value):
        declared: sview = easm_register_operand(value[equals + 1.usize():sview_len(value)])
        if easm_equal(declared, register):
            return true
return false
"""
if compact(function_body(provenance, "easm_contract_has_register")) != compact(expected_register_matcher):
    raise SystemExit("register contracts no longer use exact tokens or exact named-binding equality")

expected_exact_matcher = """
for value in values:
    cursor: mutable usize = 0
    while cursor < sview_len(value) |cursor, value, needle|:
        while cursor < sview_len(value) and (sview_at(value, cursor) == 32 or sview_at(value, cursor) == 9 or sview_at(value, cursor) == 44):
            cursor <- cursor + 1
        break if cursor >= sview_len(value)
        end: mutable usize = cursor
        while end < sview_len(value) and sview_at(value, end) != 44 |end, value|:
            end <- end + 1
        true return if easm_equal(easm_trim(value[cursor:end]), needle)
        break if end >= sview_len(value)
        cursor <- end + 1.usize()
return false
"""
if compact(function_body(provenance, "easm_contract_has_exact")) != compact(expected_exact_matcher):
    raise SystemExit("exact contract matcher changed; review the proof-to-source connection")

memory = MEMORY.read_text()
raw_guard = "not easm_contract_has_word(fn.requires, \"memory.base.untyped\")"
if memory.count(raw_guard) != 3:
    raise SystemExit("raw memory-base checks no longer use the exact contract-word guard")
function = FUNCTION.read_text()
if "not easm_contract_has_word(fn.requires, capability)" not in function:
    raise SystemExit("EASM capability admission no longer uses exact contract-word matching")

positive_text = POSITIVE.read_text()
expected_declarations = {
    "model_raw_memory_base_rejected",
    "exact_contract_member_is_recognized",
    "substring_only_is_not_an_exact_contract_member",
    "raw_memory_base_requires_exact_opt_out",
    "substring_decoy_does_not_exempt_raw_memory_base",
    "exact_opt_out_exempts_raw_memory_base",
    "typed_pointer_is_not_rejected_by_raw_guard",
    "model_register_contract_member",
    "exact_register_token_is_recognized",
    "named_register_binding_is_recognized",
    "substring_register_decoy_is_not_recognized",
    "delimiter_successor_stays_within_view",
}
actual_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text))
if actual_declarations != expected_declarations:
    raise SystemExit("positive exact-membership proof declarations changed")
if "ensure result == (raw_scalar and not exact_untyped_opt_out)" not in positive_text:
    raise SystemExit("raw memory-base proof no longer states the rejection predicate")
negative_text = NEGATIVE.read_text()
expected_false_claims = {
    "substring_decoy_exempts_raw_memory_base",
    "substring_register_decoy_is_a_declaration",
    "terminal_scan_cursor_can_advance_within_view",
}
negative_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text))
if negative_declarations != expected_false_claims:
    raise SystemExit("the exact-membership false-claim controls changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM contract-membership proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    PROVENANCE,
    MEMORY,
    FUNCTION,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 24
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == expected_declarations

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 6 and negative["summary"]["proven"] == 3
false_claims = expected_false_claims
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in false_claims
}
assert not false_claims & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact EASM word/register membership and raw-memory-base opt-out admission",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(false_claims),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
