"""Bind fail-closed caller-region slot proofs to direct-call construction."""
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
SOURCE = ROOT / "src/backend/codegen_call_direct.elisa"
CALL_FACADE = ROOT / "src/backend/codegen_call.elisa"
POSITIVE = HERE / "backend_caller_region_slots.elisa"
NEGATIVE = HERE / "backend_caller_region_slots_rejected.elisa"
POSITIVE_HASHES = {
    "caller_region_call_is_admitted": "01b559b71bda328b2abb8a2a7b1375787105bdbfb10b9237e5e8abcdcfa0c757",
    "missing_required_arena_rejects_call": "af3faa0115055157186c3c6ba3c7eaafe07a69cbf20d2710d5487b857013847c",
}
NEGATIVE_HASHES = {
    "false_call_accepts_missing_required_arena": "f2ac16bdf5bda96d2a9d9887ab1c372ed1de7ec7b53cfc1a30a4373111688b42",
}
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}(?:\[[^\n]*?\])?\(", text)
    if not match:
        raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*(?:\[[^\n]*?\])?\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
for path, expected in ((POSITIVE, POSITIVE_HASHES), (NEGATIVE, NEGATIVE_HASHES)):
    text = path.read_text()
    for name, digest in expected.items():
        if hashlib.sha256(compact(section(text, name)).encode()).hexdigest() != digest:
            raise SystemExit(f"{name} proof changed since source binding")
if not NEGATIVE.read_text().startswith('include "./backend_caller_region_slots.elisa"'):
    raise SystemExit("false control must include the positive region-slot policy")
body = compact(section(SOURCE.read_text(), "emit_direct_call_indexed"))
if 'include "./codegen_call_direct.elisa"' not in CALL_FACADE.read_text():
    raise SystemExit("direct-call implementation is no longer included by the production call facade")
ordered = (
    "continueifnotfunction_parameter_has_region(fns,fn_index,parameter_position)",
    "returnnullifllvm_value_is_null(direct_arena)",
    "argument_values.push(direct_arena)",
    "direct_arena_slot<-direct_arena_slot+1",
    "whiledirect_arena_slot<arena_count|argument_values,direct_arena_slot,call_threaded_arena|:argument_values.push(call_threaded_arena)",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("caller-region slots must reject null required arenas before push, then fill remaining slots")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("caller-region slot proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, CALL_FACADE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations"):
    raise SystemExit("caller-region slot obligations did not fully prove")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("null-arena false control was not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("caller-region proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
