"""Admit the source-pinned boolean model for the backend's inline opaque C sizes."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"
MODEL_SOURCE = ROOT / "src/backend/codegen_opaque_host_size.elisa"
TYPE_SOURCE = ROOT / "src/backend/codegen_opaque_type_size.elisa"
ASSEMBLY = ROOT / "src/backend/codegen.elisa"
EXTERN_SOURCE = ROOT / "src/backend/codegen_declare_extern.elisa"
POSITIVE = HERE / "codegen_opaque_host_size.elisa"
NEGATIVE = HERE / "codegen_opaque_host_size_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


def compact(text: str) -> str:
    without_comments = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return re.sub(r"\s+", "", without_comments)


def function_chunk(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\s*\(", text)
    if not match:
        raise AssertionError(f"function not found: {name}")
    following = re.search(r"(?m)^[ \t]*def ", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


model_text = MODEL_SOURCE.read_text()
type_text = TYPE_SOURCE.read_text()
assembly_text = ASSEMBLY.read_text()
extern_text = EXTERN_SOURCE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

size_constants = {
    "PTHREAD_MUTEX_HOST_BYTES": 64,
    "PTHREAD_COND_HOST_BYTES": 48,
    "PTHREAD_ONCE_HOST_BYTES": 16,
    "UNKNOWN_OPAQUE_HOST_BYTES": -1,
}
for const_name, value in size_constants.items():
    declaration = re.search(rf"(?m)^\s*const {const_name}: i64 = (-?[0-9]+)\s*$", model_text)
    if declaration is None or int(declaration.group(1)) != value:
        raise SystemExit(f"source ABI constant {const_name} no longer equals {value}")
    proof_declaration = re.search(rf"(?m)^const EXPECTED_{const_name}: i64 = (-?[0-9]+)\s*$", positive_text)
    if proof_declaration is None or int(proof_declaration.group(1)) != value:
        raise SystemExit(f"independent proof specification for {const_name} no longer equals {value}")

expected_size_rule = """
PTHREAD_MUTEX_HOST_BYTES if is_mutex else
(PTHREAD_COND_HOST_BYTES if is_cond else
(PTHREAD_ONCE_HOST_BYTES if is_once else UNKNOWN_OPAQUE_HOST_BYTES))
"""
expected_model_contract = """
    (
    (not is_mutex or result == PTHREAD_MUTEX_HOST_BYTES)
        and (is_mutex or not is_cond or result == PTHREAD_COND_HOST_BYTES)
        and (is_mutex or is_cond or not is_once or result == PTHREAD_ONCE_HOST_BYTES)
        and (is_mutex or is_cond or is_once or result == UNKNOWN_OPAQUE_HOST_BYTES)
    )
"""
expected_model_function = f"""
def c_opaque_host_size_from_flags(is_mutex: bool, is_cond: bool, is_once: bool) -> i64:
    ensure {expected_model_contract}
    return ({expected_size_rule})
"""
if compact(function_chunk(model_text, "c_opaque_host_size_from_flags")) != compact(expected_model_function):
    raise SystemExit("boolean size model changed from the proved nested-branch rule")

expected_type_adapter = compact("""
def c_opaque_host_size_for_type(ctype: sview) -> i64 can[Abort.Panic]:
    return when ctype:
        "pthread_mutex_t" -> BackendOpaqueHostSize::c_opaque_host_size_from_flags(true, false, false)
        "pthread_cond_t" -> BackendOpaqueHostSize::c_opaque_host_size_from_flags(false, true, false)
        "pthread_once_t" -> BackendOpaqueHostSize::c_opaque_host_size_from_flags(false, false, true)
        _ -> BackendOpaqueHostSize::c_opaque_host_size_from_flags(false, false, false)
""")
if compact(function_chunk(type_text, "c_opaque_host_size_for_type")) != expected_type_adapter:
    raise SystemExit("source string match no longer maps each type to its one-hot size-model flags")

expected_wrapper = compact("""
def c_opaque_host_size(decorators: darray[Ast::Annotation]&, annotation_args: darray[sview]&) -> i64 can[Abort.Panic]:
    for decorator in decorators |annotation_args|:
        if decorator.name == "c_opaque" and decorator.arg_count >= 2 and decorator.arg_start.usize() + 1 < annotation_args.count:
            ctype: sview = annotation_args[decorator.arg_start.usize() + 1]
            known_size: i64 = BackendOpaqueTypeSize::c_opaque_host_size_for_type(ctype)
            return known_size if known_size >= 0
    return -1
""")
if compact(function_chunk(extern_text, "c_opaque_host_size")) != expected_wrapper:
    raise SystemExit("extern annotation selection no longer delegates exactly to the type adapter")
for include in (
    'include "./codegen_opaque_host_size.elisa"',
    'include "./codegen_opaque_type_size.elisa"',
):
    if assembly_text.count(include) != 1:
        raise SystemExit(f"backend assembly must include exactly one model adapter: {include}")

expected_universal_theorem = f"""
def every_boolean_flag_tuple_uses_the_exact_size_rule(is_mutex: bool, is_cond: bool, is_once: bool) -> i64:
    ensure (
        (not is_mutex or result == EXPECTED_PTHREAD_MUTEX_HOST_BYTES)
        and (is_mutex or not is_cond or result == EXPECTED_PTHREAD_COND_HOST_BYTES)
        and (is_mutex or is_cond or not is_once or result == EXPECTED_PTHREAD_ONCE_HOST_BYTES)
        and (is_mutex or is_cond or is_once or result == EXPECTED_UNKNOWN_OPAQUE_HOST_BYTES)
    )
    return BackendOpaqueHostSize::c_opaque_host_size_from_flags(is_mutex, is_cond, is_once)
"""
if compact(function_chunk(positive_text, "every_boolean_flag_tuple_uses_the_exact_size_rule")) != compact(expected_universal_theorem):
    raise SystemExit("universal theorem no longer proves the exact boolean size rule through the source model")

registration = compact(function_chunk(extern_text, "register_one_opaque_extern"))
if registration.count("c_opaque_host_size(decorators,annotation_args)") != 1:
    raise SystemExit("opaque alias registration no longer consults the proved wrapper exactly once")
if "ifopaque_size<=0:" not in registration or "intern_array_type(ValueType{kind:TypeKind.Unsigned,bits:8},opaque_size.u32(),structs)" not in registration:
    raise SystemExit("positive opaque host sizes no longer determine the registered inline byte-array alias")

positive_names = {
    "every_boolean_flag_tuple_uses_the_exact_size_rule",
    "supported_inline_opaque_types_have_exact_sizes",
    "no_supported_type_flag_uses_the_unknown_sentinel",
}
negative_names = {
    "mutex_flag_cannot_claim_pointer_size",
    "no_type_flags_cannot_guess_an_inline_size",
}
declarations = lambda text: set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("opaque host-size theorem inventory changed")
source_include = 'include "../../src/backend/codegen_opaque_host_size.elisa"'
if source_include not in positive_text or source_include not in negative_text:
    raise SystemExit("positive and rejected proofs must each include the model source directly")
if 'include "./codegen_opaque_host_size.elisa"' in negative_text:
    raise SystemExit("rejected proof must not import the positive theorem module")
if "BackendOpaqueHostSize::c_opaque_host_size_from_flags" not in positive_text:
    raise SystemExit("proof no longer invokes the production boolean size model")
if 'include "../../src/backend/codegen_opaque_type_size.elisa"' in positive_text or 'include "../../src/backend/codegen_opaque_type_size.elisa"' in negative_text:
    raise SystemExit("proof must not claim the unmodeled source-string adapter is replayed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("opaque host-size proof requires a strict proof build")


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


inputs = [
    *source_include_closure([POSITIVE, NEGATIVE]),
    BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, MODEL_SOURCE, TYPE_SOURCE, ASSEMBLY, EXTERN_SOURCE,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}

assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-pinned one-hot pthread inline opaque C size mapping and extern alias consumer",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
