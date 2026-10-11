"""Admit source-linked proofs of the TypeScript types emitted for WASM exports."""
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
POSITIVE = HERE / "wasm_typescript_type.elisa"
NEGATIVE = HERE / "wasm_typescript_type_rejected.elisa"
TYPES = ROOT / "src/driver/wasm_typescript_type.elisa"
SCALAR = ROOT / "src/driver/wasm_scalar_wasm_type.elisa"
BINDINGS = ROOT / "src/driver/emit_wasm_bindings.elisa"
EXPORTS = ROOT / "src/driver/emit_wasm_exports.elisa"
EMITTER = ROOT / "src/driver/emit_wasm.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact_source(text: str) -> str:
    # Keep spaces inside string literals: "string | number" is a single API type.
    return re.sub(r'"(?:\\.|[^"\\])*"|\s+',
                  lambda match: match.group(0) if match.group(0).startswith('"') else "",
                  text)


types_text = compact_source(TYPES.read_text())
expected_arms = (
    '"cstr"->("string | number"ifparameterelse"string")',
    '"i64"|"u64"|"char"->"bigint"',
    '"bool"->"boolean"',
    '"void"->"void"',
    '_->"number"',
)
if "returnwhentype_text:" not in types_text:
    raise SystemExit("TypeScript mapping no longer uses pattern matching")
bigint_arms = (
    '"i64"|"u64"|"char"->true',
    '_->false',
)
pattern_arms = types_text.count("->") - types_text.count("->sview") - types_text.count("->bool")
expected_pattern_arms = len(expected_arms) + len(bigint_arms)
if any(types_text.count(arm) != 1 for arm in expected_arms) or pattern_arms != expected_pattern_arms:
    raise SystemExit("TypeScript implementation no longer matches the exact closed result table")
if "defwasm_ts_input_requires_bigint(type_text:sview)->bool:" not in types_text:
    raise SystemExit("WASM input conversion classifier is missing")
if any(types_text.count(arm) != 1 for arm in bigint_arms):
    raise SystemExit("WASM input conversion implementation no longer matches the i64 type set")
typescript_contracts = tuple(compact_source(clause) for clause in (
    'ensure (result == "string | number") == (type_text == "cstr" and parameter)',
    'ensure (result == "string") == (type_text == "cstr" and not parameter)',
    'ensure (result == "bigint") == (type_text == "i64" or type_text == "u64" or type_text == "char")',
    'ensure (result == "boolean") == (type_text == "bool")',
    'ensure (result == "void") == (type_text == "void")',
    'ensure (result == "number") == (type_text != "cstr" and type_text != "i64" and type_text != "u64" and type_text != "char" and type_text != "bool" and type_text != "void")',
))
positive_text = compact_source(POSITIVE.read_text())
if any(contract not in types_text or contract not in positive_text for contract in typescript_contracts):
    raise SystemExit("WASM TypeScript contracts and proof do not share the exact equality specification")
bigint_input_contract = compact_source(
    'ensure result == (type_text == "i64" or type_text == "u64" or type_text == "char")'
)
if bigint_input_contract not in types_text:
    raise SystemExit("WASM BigInt input classifier has no exact logical contract")

bindings_text = compact_source(BINDINGS.read_text())
exports_text = compact_source(EXPORTS.read_text())
emitter_text = compact_source(EMITTER.read_text())
driver_text = compact_source(DRIVER.read_text())
if 'include"./wasm_typescript_type.elisa"' not in bindings_text:
    raise SystemExit("WASM binding builder no longer imports the proved TypeScript mapping")
if "returnWasmTypeScriptType::wasm_ts_type(type_text,parameter)" not in bindings_text:
    raise SystemExit("WASM binding helper no longer delegates to the proved TypeScript table")
if "ifWasmTypeScriptType::wasm_ts_input_requires_bigint(type_text):" not in bindings_text:
    raise SystemExit("WASM JavaScript input generation no longer uses the proved BigInt classifier")
if 'ifWasmTypeScriptType::wasm_ts_input_requires_bigint(type_text):emit_tokens_push_sview(buffer,"BigInt(")emit_tokens_push_sview(buffer,name)emit_tokens_push_sview(buffer,")")return' not in bindings_text:
    raise SystemExit("WASM BigInt classifier no longer wraps the actual JS argument in BigInt(...)")
if "wasm_ts_type(type_view,true)" not in exports_text or "wasm_ts_type(return_view,false)" not in exports_text:
    raise SystemExit("WASM declaration generation no longer uses the proved parameter and return mappings")
if 'include"./emit_wasm_bindings.elisa"' not in emitter_text or 'include"./emit_wasm_exports.elisa"' not in emitter_text:
    raise SystemExit("WASM emitter no longer connects the proved mapping to export generation")
if 'include"./emit_wasm.elisa"' not in driver_text:
    raise SystemExit("compiler driver no longer imports the proved WASM declaration path")
for proof in (POSITIVE, NEGATIVE):
    if 'include"../../src/driver/wasm_typescript_type.elisa"' not in compact_source(proof.read_text()):
        raise SystemExit(f"{proof.name} no longer imports production TypeScript mapping code")
    if 'include"../../src/driver/wasm_scalar_wasm_type.elisa"' not in compact_source(proof.read_text()):
        raise SystemExit(f"{proof.name} no longer imports production WASM ABI scalar mapping code")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("WASM TypeScript mapping proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, TYPES, SCALAR, BINDINGS, EXPORTS, EMITTER, DRIVER,
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
assert positive == run(POSITIVE)[1], "WASM TypeScript mapping report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "wasm_ts_type",
    "source_typescript_mapping_is_exact",
    "cstr_parameter_and_return_types_are_distinct",
    "scalar_integer_bool_and_void_types_are_exact",
    "other_scalar_types_default_to_number",
    "wasm_i64_abi_types_are_typescript_bigints",
    "typescript_bigints_use_the_wasm_i64_abi",
    "bigint_input_conversion_matches_the_typescript_parameter_type",
} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == {
    "u32_must_not_use_bigint",
    "cstr_return_must_not_accept_a_numeric_address",
    "wasm_i32_abi_values_must_be_typescript_bigints",
    "u32_input_must_use_bigint",
}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed TypeScript mapping and its bidirectional coherence with the WASM i64 ABI",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [
        "u32_must_not_use_bigint",
        "cstr_return_must_not_accept_a_numeric_address",
        "wasm_i32_abi_values_must_be_typescript_bigints",
        "u32_input_must_use_bigint",
    ],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
