"""Bind homogeneous floating aggregate proofs to C ABI leaf classification."""
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
POSITIVE = HERE / "backend_cabi_hfa.elisa"
NEGATIVE = HERE / "backend_cabi_hfa_rejected.elisa"
POSITIVE_HASHES = {
    "cabi_hfa_count_policy": "5a3d65a978fe24538939005a494e08a0755fe9ea11f1f92b4fb049ff2ae89b50",
    "one_float_leaf_is_an_hfa": "dc703064fa89695949b2ee9ca0f21992e93df33fbd12c6654f0d351a56404d9c",
    "four_float_leaves_are_the_maximum_hfa": "fbee54b27c49b7dd1a5c82429f0533fb656de6ea1a476765e4009c6001119223",
    "a_fifth_float_leaf_is_not_an_hfa": "22d4c1ff80d0820e5734120ab29e1a5f4e35db14c879ca245ea5688ac76ea0d4",
}
NEGATIVE_HASHES = {
    "false_fifth_leaf_is_hfa": "63f2ea3eb7454db3a9407b530bca9cfa9fe67ceacdcf81b57b01d95af84dccce",
    "false_integer_first_leaf_is_hfa": "ee989537c43bd0f4d48b4500e7a58343a58561ddbc824d1ffb3054a8c4e1bd22",
    "false_gap_in_hfa_is_accepted": "e71bd3564ffaabb2e8d9227ff93d701a4aca13737cc52611f207f29a44e5f425",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_hfa.elisa"'):
    raise SystemExit("false controls must import the HFA policy model")
hfa = compact(section(SOURCE.read_text(), "cabi_hfa_count"))
ordered = (
    "return0ifleaves.count==0orleaves.count>4",
    "leaf_kind:i32=leaves[0].kind",
    "return0ifleaf_kind==0",
    "forleaf_indexin0..<leaves.count|leaves,leaf_kind|:",
    "return0ifleaves[leaf_index].kind!=leaf_kindorleaves[leaf_index].offset!=leaf_index.u64()*leaves[leaf_index].size",
    "returnleaves.count",
)
if any(part not in hfa for part in ordered) or [hfa.index(part) for part in ordered] != sorted(hfa.index(part) for part in ordered):
    raise SystemExit("HFA count must enforce size, floating leaf, uniform kind, and contiguous offsets")
argument = compact(section(SOURCE.read_text(), "cabi_classify_arg"))
returned = compact(section(SOURCE.read_text(), "cabi_classify_ret_llvm"))
if "hfa:usize=cabi_hfa_count(leaves)" not in argument or "ifhfa>0:" not in argument:
    raise SystemExit("aggregate argument classifier no longer prefers HFA register parts")
if "ifcabi_hfa_count(leaves)>0" not in returned:
    raise SystemExit("aggregate return classifier no longer recognizes HFA returns")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("HFA proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("HFA policy obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("HFA false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("HFA proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
