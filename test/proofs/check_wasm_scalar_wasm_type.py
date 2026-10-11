"""Admit source-linked proofs of the scalar type mapping used by WASM exports."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "wasm_scalar_wasm_type.elisa"
NEGATIVE = HERE / "wasm_scalar_wasm_type_rejected.elisa"
SCALAR = ROOT / "src/driver/wasm_scalar_wasm_type.elisa"
BINDINGS = ROOT / "src/driver/emit_wasm_bindings.elisa"
EXPORTS = ROOT / "src/driver/emit_wasm_exports.elisa"
EMITTER = ROOT / "src/driver/emit_wasm.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    # This source contains no whitespace-bearing string literals.
    return re.sub(r"\s+", "", text)


scalar_text = compact(SCALAR.read_text())
expected_arms = (
    '"i8"|"u8"|"i16"|"u16"|"i32"|"u32"|"int"|"isize"|"usize"|"uintptr"|"bool"->"i32"',
    '"i64"|"u64"|"char"->"i64"',
    '"f32"->"f32"',
    '"f64"->"f64"',
    '"void"->"void"',
    '_->""',
)
if "returnwhentype_text:" not in scalar_text:
    raise SystemExit("WASM scalar helper no longer implements a pattern table")
contract_clauses = (
    'ensure(result=="i32")==(' + 'type_text=="i8"ortype_text=="u8"ortype_text=="i16"ortype_text=="u16"ortype_text=="i32"ortype_text=="u32"ortype_text=="int"ortype_text=="isize"ortype_text=="usize"ortype_text=="uintptr"ortype_text=="bool")',
    'ensure(result=="i64")==(' + 'type_text=="i64"ortype_text=="u64"ortype_text=="char")',
    'ensure(result=="f32")==(' + 'type_text=="f32")',
    'ensure(result=="f64")==(' + 'type_text=="f64")',
    'ensure(result=="void")==(' + 'type_text=="void")',
    'ensure(result=="")==(' + 'type_text!="i8"andtype_text!="u8"andtype_text!="i16"andtype_text!="u16"andtype_text!="i32"andtype_text!="u32"andtype_text!="int"andtype_text!="isize"andtype_text!="usize"andtype_text!="uintptr"andtype_text!="bool"andtype_text!="i64"andtype_text!="u64"andtype_text!="char"andtype_text!="f32"andtype_text!="f64"andtype_text!="void")',
)
pattern_arms = scalar_text.count("->") - scalar_text.count("->sview")
if any(scalar_text.count(arm) != 1 for arm in expected_arms) or pattern_arms != len(expected_arms):
    raise SystemExit("WASM scalar implementation no longer matches the exact closed mapping")
positive_text = compact(POSITIVE.read_text())
if any(clause not in scalar_text or clause not in positive_text for clause in contract_clauses):
    raise SystemExit("WASM scalar contract and proof do not share the supported exact equality specification")

bindings_text = compact(BINDINGS.read_text())
exports_text = compact(EXPORTS.read_text())
emitter_text = compact(EMITTER.read_text())
driver_text = compact(DRIVER.read_text())
if 'include"./wasm_scalar_wasm_type.elisa"' not in bindings_text:
    raise SystemExit("WASM binding builder no longer imports the proved scalar mapping")
if "returnWasmScalarWasmType::wasm_scalar_wasm_type(type_text)" not in bindings_text:
    raise SystemExit("WASM binding helper no longer delegates to the proved table")
if "scalar:sview=wasm_scalar_wasm_type(type_text)" not in bindings_text:
    raise SystemExit("WASM ABI binding no longer uses the proved scalar table")
if 'include"./emit_wasm_bindings.elisa"' not in emitter_text or 'include"./emit_wasm_exports.elisa"' not in emitter_text:
    raise SystemExit("WASM emitter no longer connects the proved binding helper to exports")
if "wasm_abi_binding(" not in exports_text:
    raise SystemExit("WASM export generation no longer consults the ABI binding helper")
if 'include"./emit_wasm.elisa"' not in driver_text:
    raise SystemExit("compiler driver no longer imports the proved WASM export path")
for proof in (POSITIVE, NEGATIVE):
    if 'include"../../src/driver/wasm_scalar_wasm_type.elisa"' not in compact(proof.read_text()):
        raise SystemExit(f"{proof.name} no longer imports production WASM scalar code")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("WASM scalar mapping proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, SCALAR, BINDINGS, EXPORTS, EMITTER, DRIVER,
]
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "WASM scalar mapping report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "wasm_scalar_wasm_type",
    "source_scalar_mapping_is_exact",
    "integer_scalar_names_use_i32",
    "wider_and_non_integer_scalars_keep_their_wasm_types",
    "unknown_scalar_names_have_no_wasm_type",
} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == {
    "f64_must_not_be_narrowed_to_f32",
    "unlisted_scalar_must_not_receive_an_abi_type",
}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed scalar type mapping used by WASM export binding generation",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["f64_must_not_be_narrowed_to_f32", "unlisted_scalar_must_not_receive_an_abi_type"],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
