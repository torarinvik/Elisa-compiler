"""Bind noalias eligibility proofs to backend type, mutability, and opt-in gates."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=not args.source_only)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
ATTRS = ROOT / "src/backend/codegen_attrs.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
POSITIVE = HERE / "backend_noalias_eligibility.elisa"
NEGATIVE = HERE / "backend_noalias_eligibility_rejected.elisa"
POSITIVE_NAMES = {"noalias_pointee_is_eligible", "mutable_scalar_parameter_receives_noalias", "noalias_is_disabled_without_explicit_opt_in"}
NEGATIVE_NAMES = {"false_aggregate_reference_gets_noalias", "false_immutable_reference_gets_noalias", "false_heap_reference_gets_noalias"}
PROOF_HASHES = {
"noalias_pointee_is_eligible": "515887f42196e5fa79a1a5d8f460edd2dfa26f5839c4babf7e916eaaa01b7c2c",
"mutable_scalar_parameter_receives_noalias": "cad94405161e899d3d0a6ed13c84cd8eeb6511832975e417335ce8c065560c28",
"noalias_is_disabled_without_explicit_opt_in": "45c8b92f51db87ddc50ff8d85295e52e8b5fbf249868d821af759f5c0970ef38",
"false_aggregate_reference_gets_noalias": "4a3cc95fd7a70589aeff1a25f4f12e14ee006e0d5b62c73e137f27fc941c8310",
"false_immutable_reference_gets_noalias": "861f5bcaacd057700af95a156541acad7915c75212d3a59b1dcd53e54872357a",
"false_heap_reference_gets_noalias": "d90bb5e7f0c6b3fd05002a62a104794855376e578c88e56cd136e7c3d6a90eef",
}
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1: raise SystemExit(f"expected one {name} declaration")
    m = matches[0]; indent = m.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[m.end():])
    return source[m.start():m.end()+following.start() if following else len(source)]
def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
attrs, env = ATTRS.read_text(), ENV.read_text()
pointee = compact(section(attrs, "noalias_pointee_eligible"))
for shape in ("value_type.kind!=TypeKind.Ref", "ref_is_heap_ref(value_type,structs)", "ref_target_of(value_type,structs)", "is_numeric_type(pointee)"):
    if shape not in pointee: raise SystemExit(f"noalias pointee eligibility lost gate: {shape}")
mutable = compact(section(attrs, "type_outer_reference_is_mutable"))
if "operator==TokenKind.Mutable" not in mutable or "operator==TokenKind.Ampersand" not in mutable:
    raise SystemExit("outer-reference mutability must stop at the first ampersand")
apply = compact(section(attrs, "apply_noalias_parameter_attributes"))
for shape in ("notstructs.target.noalias_mutable_refs", "parameter_type.kind==TypeKind.Ref", "type_outer_reference_is_mutable(parameter.type_expression)", "noalias_pointee_eligible(parameter_type,structs)", '"noalias"'):
    if shape not in apply: raise SystemExit(f"noalias emission lost gate: {shape}")
if 'sview_to_cstr("ELISACORE_NOALIAS_MUTABLE_REFS"' not in compact(section(env, "noalias_mutable_refs_enabled")):
    raise SystemExit("noalias feature must remain behind the explicit environment opt-in")
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("noalias eligibility proof inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_noalias_eligibility.elisa"'):
    raise SystemExit("noalias false controls must include the positive eligibility model")
for name, expected in PROOF_HASHES.items():
    owner = POSITIVE if name in POSITIVE_NAMES else NEGATIVE
    actual = hashlib.sha256(compact(section(owner.read_text(), name)).encode()).hexdigest()
    if actual != expected: raise SystemExit(f"noalias theorem {name} changed since source binding")
if args.source_only:
    print(json.dumps({"source_bound": True, "positive": len(POSITIVE_NAMES), "false_controls": len(NEGATIVE_NAMES)})); raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict": raise SystemExit("noalias eligibility proof requires a strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", ATTRS, ENV, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
def run(path: Path) -> tuple[int, dict]:
    p = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return p.returncode, json.loads(p.stdout)
code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert {r["name"] for r in positive["declaration_details"] if r.get("verified")} == POSITIVE_NAMES
code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {r["name"] for r in negative["findings"]} == NEGATIVE_NAMES
assert all(r["kind"] == "ensure-unproven" and r["status"] in ("unknown", "disproved") for r in negative["findings"])
if {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs} != before: raise SystemExit("proof inputs changed during replay")
print(json.dumps({"positive_obligations": positive["summary"]["proven"], "false_claims_rejected": sorted(NEGATIVE_NAMES), "source_bound": True}))
