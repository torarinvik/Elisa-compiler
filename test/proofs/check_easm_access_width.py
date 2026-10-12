"""Admit source-backed proofs of EASM opcode memory access widths."""
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
POSITIVE = HERE / "easm_access_width.elisa"
NEGATIVE = HERE / "easm_access_width_rejected.elisa"
HELPER = ROOT / "src/backend/easm_access_width.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
FUNCTIONS = ROOT / "src/backend/easm_verify_function.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


width_cases = (
    ("movb", 1), ("xchgb", 1),
    ("movw", 2), ("xchgw", 2),
    ("movl", 4), ("xchgl", 4),
    ("movq", 8), ("xchgq", 8),
)
helper_text = compact(HELPER.read_text())
partition = (
    '1 if (op == "movb" or op == "xchgb") else '
    '2 if (op == "movw" or op == "xchgw") else '
    '4 if (op == "movl" or op == "xchgl") else '
    '8 if (op == "movq" or op == "xchgq") else 0'
)
if compact(f"ensure result == ({partition})") not in helper_text:
    raise SystemExit("production width contract no longer states the exact opcode-token partition")
match_table = (
    '"movb" | "xchgb" -> 1 '
    '"movw" | "xchgw" -> 2 '
    '"movl" | "xchgl" -> 4 '
    '"movq" | "xchgq" -> 8 '
    "_ -> 0"
)
if compact(f"return when op: {match_table}") not in helper_text:
    raise SystemExit("production classifier no longer uses the reviewed exact opcode match table")
proof_text = compact(POSITIVE.read_text())
effectful_proofs = (
    "def access_width_matches_the_exact_opcode_partition(op: sview) -> bool can[Abort.Panic]:",
    "def byte_access_opcodes_have_width_one() -> bool can[Abort.Panic]:",
    "def word_access_opcodes_have_width_two() -> bool can[Abort.Panic]:",
    "def dword_access_opcodes_have_width_four() -> bool can[Abort.Panic]:",
    "def qword_access_opcodes_have_width_eight() -> bool can[Abort.Panic]:",
    "def nonsized_opcodes_and_prefix_lookalikes_have_no_memory_access_width() -> bool can[Abort.Panic]:",
)
if any(compact(signature) not in proof_text for signature in effectful_proofs):
    raise SystemExit("proof callers no longer declare the production classifier's Abort.Panic effect")
proof_source = POSITIVE.read_text()
for signature in effectful_proofs:
    name = re.search(r"def ([A-Za-z_][A-Za-z0-9_]*)\(", signature).group(1)
    start = re.search(rf"(?m)^def {re.escape(name)}\(", proof_source)
    following = re.search(r"(?m)^def [A-Za-z_][A-Za-z0-9_]*\(", proof_source[start.end():])
    end = start.end() + following.start() if following else len(proof_source)
    body = compact(proof_source[start.end():end])
    grant = body.find("canAbort.Panic:")
    call = body.find("EasmAccessWidth::access_width(")
    if grant < 0 or call < 0 or grant > call:
        raise SystemExit(f"{name} must locally grant Abort.Panic before calling the production classifier")
proof_dispatch = (
    'return match op: '
    '"movb" | "xchgb": EasmAccessWidth::access_width(op) == 1 '
    '"movw" | "xchgw": EasmAccessWidth::access_width(op) == 2 '
    '"movl" | "xchgl": EasmAccessWidth::access_width(op) == 4 '
    '"movq" | "xchgq": EasmAccessWidth::access_width(op) == 8 '
    '_: EasmAccessWidth::access_width(op) == 0'
)
if compact(proof_dispatch) not in proof_text:
    raise SystemExit("universal width proof no longer matches every production opcode partition case")

environment = ENV.read_text()
if 'include "easm_access_width.elisa"' not in environment:
    raise SystemExit("backend environment no longer imports the proved EASM access-width module")
if environment.index('include "easm_access_width.elisa"') > environment.index('include "easm_model.elisa"'):
    raise SystemExit("EASM access-width module is imported after consumers that use its string helpers")
if 'include "../../src/backend/easm_access_width.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the production access-width module")


def require_return(source: str, declaration: str, call: str) -> None:
    body = source.split(declaration, 1)[1].split("\n\n        def ", 1)[0]
    if f"return {call}" not in body:
        raise SystemExit(f"{declaration.strip()} no longer delegates to its proved operation")


require_return(MEMORY.read_text(), "def easm_access_width(op: sview) -> i64:",
               "EasmAccessWidth::access_width(op)")
if "width: i64 = easm_access_width(instruction.op)" not in MEMORY.read_text():
    raise SystemExit("memory verification no longer uses the proved access-width classifier")
if compact("sview_len(inst.op) == 0 or not easm_known_op(inst.op)") not in compact(FUNCTIONS.read_text()):
    raise SystemExit("EASM function verification no longer rejects opcodes outside its exact operation set")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM access-width proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    HELPER,
    ENV,
    MEMORY,
    FUNCTIONS,
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "access_width",
    "access_width_matches_the_exact_opcode_partition",
    "byte_access_opcodes_have_width_one",
    "word_access_opcodes_have_width_two",
    "dword_access_opcodes_have_width_four",
    "qword_access_opcodes_have_width_eight",
    "nonsized_opcodes_and_prefix_lookalikes_have_no_memory_access_width",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "byte_access_has_dword_width")
]

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact EASM opcode-token memory access-width partition",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["byte_access_has_dword_width"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
