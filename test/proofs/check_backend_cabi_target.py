"""Bind C ABI target-selection proof to platform and environment checks."""
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
POSITIVE = HERE / "backend_cabi_target.elisa"
NEGATIVE = HERE / "backend_cabi_target_rejected.elisa"
POSITIVE_HASHES = {
    "cabi_target_policy": "0d606b1793514f5a436161b9728ed304e2563e0b4c5e528a5b840d87c03ce777",
    "wasm_target_takes_priority_over_x86_flag": "f8a89c53bc254a18a38b9002eacd193159d426b9ec64a013b1002d742e34f148",
    "x86_flag_selects_x86_when_not_wasm": "77e0ff79691324ae648cb06067795e06ecc97e0b683fc4aa1b403b638e1555a0",
    "no_wasm_or_x86_flag_selects_arm64": "dc3a4c45d432bc260883d8495fa44ebbc83d0644387ffbe1f57087cbef9ad391",
}
NEGATIVE_HASHES = {
    "false_wasm_not_selected_when_x86_enabled": "c07b78cf1cd53f941723aea52b652f5ff2c66a10af5f94811b7a3d5d0955f98a",
    "false_x86_not_selected_without_wasm": "93189b633a0f858596cf0230425e18c86f762aa83bb00ef7957ff3933e8245b4",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_target.elisa"'):
    raise SystemExit("false controls must import the target-selection model")
body = compact(section(SOURCE.read_text(), "cabi_target_from_environment"))
ordered = (
    "2returniftarget_triple_is_wasm()",
    '1returnifgetenv("ELISA_STAGE1_X86_64")isx86_target',
    "return0",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("C ABI target selection must prioritize wasm, then x86 flag, then arm64 default")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("C ABI target proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("C ABI target-selection obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("target-priority false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("C ABI target proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
