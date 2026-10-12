"""Admit the source-linked proof of the exact WASM storage-token classifier."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "wasm_storage_keyword.elisa"
NEGATIVE = HERE / "wasm_storage_keyword_rejected.elisa"
PROJECTION = HERE / "parser_token_kind_projection.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
HELPER = ROOT / "src/driver/wasm_storage_keyword.elisa"
BINDINGS = ROOT / "src/driver/emit_wasm_bindings.elisa"
EMITTER = ROOT / "src/driver/emit_wasm.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


expected_names = ["Mutable", "Lmut", "Heap", "Stack", "Static"]
source = HELPER.read_text()
match = re.search(
    r"(?ms)^\s*def is_storage_keyword\(kind: Lexer::TokenKind\) -> bool:\n(.*?)(?=^\s*def |\Z)",
    source,
)
if not match:
    raise SystemExit("production storage-keyword classifier is missing")
body = match.group(1)
arms = re.search(r"(?ms)^\s*return when kind:\n(.*)", body)
if not arms:
    raise SystemExit("production storage-keyword classifier must use a closed pattern match")
arm_lines = [line.strip() for line in arms.group(1).splitlines() if line.strip()]
if len(arm_lines) != 2 or arm_lines[-1] != "_ -> false":
    raise SystemExit("production classifier lost its exact false fallback")
expected_arm = " | ".join(f"Lexer::TokenKind.{name}" for name in expected_names) + " -> true"
if arm_lines[0] != expected_arm:
    raise SystemExit("production storage-keyword set differs from the exact source contract")

contract = "ensure result == (kind == Lexer::TokenKind.Mutable or kind == Lexer::TokenKind.Lmut or kind == Lexer::TokenKind.Heap or kind == Lexer::TokenKind.Stack or kind == Lexer::TokenKind.Static)"
for description, text in (("production", source), ("proof", POSITIVE.read_text())):
    normalized = compact(text)
    if compact(contract) not in normalized:
        raise SystemExit(f"{description} storage-keyword specification differs from the closed token set")


def enum_variants(text: str) -> list[str]:
    enum = re.search(
        r"(?ms)^\s*const enum TokenKind of u8:\n(.*?)(?=^\s*(?:struct|const enum|def) |\Z)",
        text,
    )
    if not enum:
        raise SystemExit("complete TokenKind enum is missing")
    return [line.strip() for line in enum.group(1).splitlines()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]


if enum_variants(TOKENS.read_text()) != enum_variants(PROJECTION.read_text()):
    raise SystemExit("proof TokenKind projection differs from the production enum order")
for name in expected_names + ["Ident", "Const", "Ampersand", "LShiftEq"]:
    if not re.search(rf"(?m)^\s+{name}\s*$", TOKENS.read_text()):
        raise SystemExit(f"TokenKind.{name} is missing from the production enum")

bindings = BINDINGS.read_text()
if 'include "./wasm_storage_keyword.elisa"' not in bindings:
    raise SystemExit("WASM binding builder no longer imports the proved classifier")
if "WasmStorageKeyword::is_storage_keyword(kind)" not in bindings:
    raise SystemExit("WASM type normalization no longer delegates to the proved classifier")
if 'include "./emit_wasm_bindings.elisa"' not in EMITTER.read_text():
    raise SystemExit("WASM emitter no longer connects the classifier to binding generation")
if 'include "./emit_wasm.elisa"' not in DRIVER.read_text():
    raise SystemExit("compiler driver no longer imports the WASM emitter")
if 'include "./parser_token_kind_projection.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the complete token-kind projection")
if 'include "../../src/driver/wasm_storage_keyword.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the production classifier")
if 'include "./wasm_storage_keyword.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer import the source-linked proof")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("WASM storage-keyword proof requires a strict proof build")
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
    TOKENS, PROJECTION, HELPER, BINDINGS, EMITTER, DRIVER, *source_closure,
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
assert positive == run(POSITIVE)[1], "WASM storage-keyword proof changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "is_storage_keyword",
    "source_storage_keyword_match_is_exact",
    "all_storage_qualifiers_are_recognized",
    "nearby_non_storage_tokens_are_excluded",
} <= verified

code, negative = run(NEGATIVE)
negative_names = {
    "identifier_must_not_be_a_storage_qualifier",
    "compound_shift_must_not_be_a_storage_qualifier",
}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == product_manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact Mutable/Lmut/Heap/Stack/Static classification used by WASM type normalization",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
