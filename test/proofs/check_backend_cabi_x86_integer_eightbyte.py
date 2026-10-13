"""Bind partial x86 integer eightbyte width proofs to LLVM type construction."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
SOURCE = ROOT / "src/backend/codegen_c_abi.elisa"
POSITIVE = HERE / "backend_cabi_x86_integer_eightbyte.elisa"
NEGATIVE = HERE / "backend_cabi_x86_integer_eightbyte_rejected.elisa"
POSITIVE_HASHES = {
    "x86_integer_eightbyte_width_bits": "2a3a0dd24e802a8eac5212b4a3254df307db6716c05a073b4f200dd337574c03",
    "one_byte_integer_slot_has_eight_bits": "0f69edd79e717239f450b47625ce2c29dfaa9825eda1db83d27ba3479edef2e4",
    "eight_byte_integer_slot_has_sixty_four_bits": "c052c1010edbf8b7eb6ff907e4dbdab4afea20b643afea65d6fa8f5a47285323",
    "larger_integer_slot_is_capped_at_sixty_four_bits": "7d52a2b752cd3135d78c52ae2b7526cb660549178515004ade33dad5e2100ad1",
}
NEGATIVE_HASHES = {
    "false_partial_integer_slot_has_full_width": "f5bd386148f655608fff29873f098e9bb54a25413b5c2fa618015ab3ab845852",
}
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", text)
    if not match:
        raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
for path, expected in ((POSITIVE, POSITIVE_HASHES), (NEGATIVE, NEGATIVE_HASHES)):
    text = path.read_text()
    for name, digest in expected.items():
        if hashlib.sha256(compact(section(text, name)).encode()).hexdigest() != digest:
            raise SystemExit(f"{name} proof changed since source binding")
if not NEGATIVE.read_text().startswith('include "./backend_cabi_x86_integer_eightbyte.elisa"'):
    raise SystemExit("false control must import the integer eightbyte model")
source_text = SOURCE.read_text()
body = compact(section(source_text, "cabi_x86_eightbyte"))
ordered = (
    "lo:u64=eb*8",
    "ifints>0:",
    "used:u64=(size-lo)ifsize-lo<8else8",
    "returnLLVMIntTypeInContext(ctx,(used*8).u32())",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("partial integer eightbyte must use remaining bytes and cap each slot at eight bytes")
argument_body = compact(section(source_text, "cabi_classify_arg"))
if "whileeb*8<size|eb,x86_parts,x86_offsets,leaves,size,ctx|:" not in argument_body or "cabi_x86_eightbyte(leaves,size,eb,ctx,eb_found)" not in argument_body:
    raise SystemExit("integer width helper must be called once for each in-range eightbyte")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("integer eightbyte proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("integer eightbyte obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("partial integer width false control was not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("integer eightbyte proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
