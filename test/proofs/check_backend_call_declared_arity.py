"""Bind declared call-arity proofs to the direct-call LLVM parameter guard."""
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
SOURCE = ROOT / "src/backend/codegen_call.elisa"
POSITIVE = HERE / "backend_call_declared_arity.elisa"
NEGATIVE = HERE / "backend_call_declared_arity_rejected.elisa"
POSITIVE_HASHES = {
    "call_declared_llvm_parameter_count": "a8b6d87af5bebb5249b75e0b6995b09829ec0ecaa78fafe7340c00ac4e84d73d",
    "defaulted_call_uses_fixed_signature_count": "5bb4c79373107b0dff1ddfefe40509ad1be4004ab6610cf739298ed570e9d376",
    "variadic_call_uses_fixed_signature_count": "81fae264f98cf412661b0e92b7d81013a2b19f0d3f6cea48b20ee0508317b7a7",
    "nondefaulted_fixed_call_uses_supplied_count": "dc953581a128c09eafda0e9178126866e7eab2fedb66896706db6c1520c4b9c1",
}
NEGATIVE_HASHES = {
    "false_defaulted_call_uses_supplied_count": "953a0eb1729158ff99bf5c5e37a2e19d4e2afcc9991505a0d2a22c1f26aab6d0",
    "false_error_call_omits_hidden_parameter": "e28aef3ebe1f3c916cb9fbe2a784705c4363abd1a981560eb93950f8a1d257be",
    "false_c_view_split_omitted": "2a8d5005c60b80037643aa8844496d60e2b60246bc4c5f621a7fd16d98f5f6a9",
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
if not NEGATIVE.read_text().startswith('include "./backend_call_declared_arity.elisa"'):
    raise SystemExit("false controls must import the call-arity model")
body = compact(section(SOURCE.read_text(), "emit_direct_call_indexed"))
ordered = (
    "uses_defaults:bool=notvariadic_callandtotal_arguments<fixed_arguments",
    "expected_params:mutableusize=fixed_arguments+arena_count+(1ifwants_storeelse0)+(1ifsret_returnelse0)ifvariadic_calloruses_defaultselsetotal_arguments+arena_count+(1ifwants_storeelse0)+(1ifsret_returnelse0)",
    "expected_params<-expected_params+1iffns.is_error[fn_index.usize()]",
    "expected_params<-expected_params+1ifextern_error_sret",
    "LLVMCountParams(target).i64()!=(expected_params+split_view_params).i64()",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("direct-call declared-parameter count policy changed")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("call arity proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations"):
    raise SystemExit("call declared-arity obligations did not fully prove")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("call arity false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("call-arity proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
