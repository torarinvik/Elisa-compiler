"""Admit the source-linked proof of WASM export type classification."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "wasm_abi_type_classification.elisa"
NEGATIVE = HERE / "wasm_abi_type_classification_rejected.elisa"
SCALAR = ROOT / "src/driver/wasm_scalar_wasm_type.elisa"
CLASSIFIER = ROOT / "src/driver/wasm_abi_type_classification.elisa"
BINDINGS = ROOT / "src/driver/emit_wasm_bindings.elisa"
EXPORTS = ROOT / "src/driver/emit_wasm_exports.elisa"
EMITTER = ROOT / "src/driver/emit_wasm.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


classifier_text = compact(CLASSIFIER.read_text())
expected_fragments = (
    "constWASM_ABI_NULLABLE_SUFFIX:u8=63",
    "constWASM_ABI_POINTER_SUFFIX:u8=38",
    "return(\"\",\"\")",
    "(\"string\",\"i32\")returniftype_text==\"cstr\"",
    "(\"pointer\",\"i32\")returnifhas_suffix(type_text,WASM_ABI_POINTER_SUFFIX)",
    "(\"scalar\",scalar)returnifscalar!=\"\"",
    "(\"scalar\",\"i32\")returnifcomponent",
    "return(\"\",\"\")",
)
if any(fragment not in classifier_text for fragment in expected_fragments):
    raise SystemExit("production WASM ABI classifier no longer matches its closed case specification")
for contract in (
    'ensure(result.binding=="string")== (not has_suffix(type_text,WASM_ABI_NULLABLE_SUFFIX) and type_text=="cstr")',
    'ensure(result.binding=="pointer")== (not has_suffix(type_text,WASM_ABI_NULLABLE_SUFFIX) and has_suffix(type_text,WASM_ABI_POINTER_SUFFIX))',
    'ensure(result.binding=="scalar")== (not has_suffix(type_text,WASM_ABI_NULLABLE_SUFFIX) and type_text!="cstr" and not has_suffix(type_text,WASM_ABI_POINTER_SUFFIX) and (WasmScalarWasmType::is_scalar_type_name(type_text) or component))',
    'ensure(result.binding=="")== (has_suffix(type_text,WASM_ABI_NULLABLE_SUFFIX) or (type_text!="cstr" and not has_suffix(type_text,WASM_ABI_POINTER_SUFFIX) and not WasmScalarWasmType::is_scalar_type_name(type_text) and not component))',
    'ensure(result.wasm_type=="i32")== (result.binding=="string" or result.binding=="pointer" or (result.binding=="scalar" and (type_text=="i8" or type_text=="u8" or type_text=="i16" or type_text=="u16" or type_text=="i32" or type_text=="u32" or type_text=="int" or type_text=="isize" or type_text=="usize" or type_text=="uintptr" or type_text=="bool" or not WasmScalarWasmType::is_scalar_type_name(type_text))))',
    'ensure(result.wasm_type=="i64")== (result.binding=="scalar" and (type_text=="i64" or type_text=="u64" or type_text=="char"))',
    'ensure(result.wasm_type=="f32")== (result.binding=="scalar" and type_text=="f32")',
    'ensure(result.wasm_type=="f64")== (result.binding=="scalar" and type_text=="f64")',
    'ensure(result.wasm_type=="void")== (result.binding=="scalar" and type_text=="void")',
    'ensure(result.wasm_type=="")== (result.binding=="")',
):
    if compact(contract) not in classifier_text:
        raise SystemExit("production ABI classifier lost an exact classification contract")

bindings_text = compact(BINDINGS.read_text())
exports_text = compact(EXPORTS.read_text())
emitter_text = compact(EMITTER.read_text())
driver_text = compact(DRIVER.read_text())
if 'include"./wasm_scalar_wasm_type.elisa"' not in bindings_text:
    raise SystemExit("WASM binding builder no longer imports the scalar mapping")
if 'include"./wasm_abi_type_classification.elisa"' not in bindings_text:
    raise SystemExit("WASM binding builder no longer imports the ABI classifier")
if "WasmAbiTypeClassification::classify(type_text,component)" not in bindings_text:
    raise SystemExit("WASM binding diagnostic no longer uses the proved classifier")
if "isnullable;useanexplicitscalar/pointeradapter" not in bindings_text or "notdirectlyrepresentableinthegeneratedWASMbindings" not in bindings_text:
    raise SystemExit("WASM binding errors no longer distinguish nullable and unsupported types")
if "wasm_abi_binding(" not in exports_text:
    raise SystemExit("WASM export generation no longer consults the ABI binding")
if 'include"./emit_wasm_bindings.elisa"' not in emitter_text or 'include"./emit_wasm_exports.elisa"' not in emitter_text:
    raise SystemExit("WASM emitter no longer connects binding classification to exports")
if 'include"./emit_wasm.elisa"' not in driver_text:
    raise SystemExit("compiler driver no longer imports the WASM export path")
positive_text = compact(POSITIVE.read_text())
negative_text = compact(NEGATIVE.read_text())
if 'include"../../src/driver/wasm_scalar_wasm_type.elisa"' not in positive_text or 'include"../../src/driver/wasm_abi_type_classification.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production scalar and ABI classifiers")
if 'include"./wasm_abi_type_classification.elisa"' not in negative_text:
    raise SystemExit("negative claims no longer import the source-linked classifier proof")
for declaration in (
    "cstr_uses_the_string_i32_binding",
    "pointer_types_use_the_i32_pointer_binding",
    "scalar_types_preserve_the_canonical_wasm_type",
    "component_named_types_use_the_core_enum_representation",
    "unsupported_and_nullable_types_have_no_binding",
):
    if f"def{declaration}(" not in positive_text:
        raise SystemExit(f"positive proof lost {declaration}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("WASM ABI classification proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, BINDINGS, EMITTER, DRIVER])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    SCALAR, CLASSIFIER, BINDINGS, EXPORTS, EMITTER, DRIVER, *source_closure,
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
assert positive == run(POSITIVE)[1], "WASM ABI mapping proof changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "classify",
    "is_scalar_type_name",
    "cstr_uses_the_string_i32_binding",
    "pointer_types_use_the_i32_pointer_binding",
    "scalar_types_preserve_the_canonical_wasm_type",
    "component_named_types_use_the_core_enum_representation",
    "unsupported_and_nullable_types_have_no_binding",
} <= verified

code, negative = run(NEGATIVE)
negative_names = {
    "nullable_scalar_must_not_receive_an_abi_type",
    "unknown_non_component_type_must_not_become_scalar",
    "cstr_must_not_use_the_pointer_binding",
}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == product_manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "WASM binding classification for strings, pointers, scalars, components and unsupported types",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
