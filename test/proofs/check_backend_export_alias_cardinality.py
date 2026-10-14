"""Bind generic export alias cardinality proofs to backend type resolution."""
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
SOURCE = ROOT / "src/backend/codegen_export_aliases.elisa"
POSITIVE = HERE / "backend_export_alias_cardinality.elisa"
EXPECTED = {
    "one_ready_instance_is_resolved": "68621e265a7316e94732c833253bfab8db89955cc7db17ac45f3f9ec2a961869",
    "zero_matching_instances_are_declined": "c9683b0a71af4c69e23883db9f0efae3b4fd0a1405976c46b1f2b2a72731fca5",
    "multiple_matching_instances_are_declined": "6c7582d68aae479c2c8b9bd397ba597781e9c58a76896aee7d5146fedd26936c",
    "invalid_instance_index_is_declined": "3115322fd145f71f1f99414e2b348e709b9072327a974bc6e5e426474dbee147",
}
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", text)
    if not match: raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
for name, digest in EXPECTED.items():
    if hashlib.sha256(compact(section(POSITIVE.read_text(), name)).encode()).hexdigest() != digest:
        raise SystemExit(f"{name} proof changed since source binding")
body = compact(section(SOURCE.read_text(), "export_alias_value_type"))
required = [
    "structs.generics.generic_struct_inst_bases[inst]==base_name",
    "generic_instance_template_id(inst,structs)==expected_template",
    "structs.generics.generic_struct_inst_ready[inst]",
    "matches<-matches+1",
    "matches!=1orfound_index<0",
    "bits:found_index.u32()",
]
if any(part not in body for part in required) or [body.index(part) for part in required] != sorted(body.index(part) for part in required):
    raise SystemExit("generic export alias matching or uniqueness guard changed")
if args.source_only:
    print("source_bound=True positive=4")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict": raise SystemExit("export alias proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, *source_include_closure([POSITIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
result = subprocess.run([str(BIN), "--json", str(POSITIVE)], capture_output=True, text=True, timeout=60)
report = json.loads(result.stdout)
if result.returncode or report.get("status") != "proved" or report.get("summary", {}).get("proven") != report.get("summary", {}).get("obligations") or report.get("replay", {}).get("gaps") != 0:
    raise SystemExit("generic export alias cardinality proof did not fully replay")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("export alias proof inputs changed during replay")
print(json.dumps({"proved": report["summary"]["proven"], "source_bound": True, "replay_gaps": 0}))
