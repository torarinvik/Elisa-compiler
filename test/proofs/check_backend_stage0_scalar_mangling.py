"""Bind scalar ABI mangle branch proofs to the backend width checks."""
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
SOURCE = ROOT / "src/backend/codegen_abi_facts.elisa"
POSITIVE = HERE / "backend_stage0_scalar_mangling.elisa"
NEGATIVE = HERE / "backend_stage0_scalar_mangling_rejected.elisa"
EXPECTED = {
    "signed_i8_branch_is_exact": "1a4e2275069f74389f1529bde0e616859753d67eef9c219de7a98bb74b70f32c",
    "signed_i16_branch_is_exact": "0686e24aefead0c94f8d150332723097ab9def5644756c013ba39d88ca10d159",
    "signed_i32_branch_is_exact": "af22ce2f0b9aac3436879300e654476315998ef83bf000a61e23e85831fe0109",
    "signed_i64_branch_is_exact": "64850805c6618e8cf695cd71dddc223f4a880271b13c8db3743663bf51864642",
    "unsigned_u8_branch_is_exact": "c1c6aebf42e2da69480645a9159ad9d85996c909161b1e15b9df13d82e666ddf",
    "unsigned_u16_branch_is_exact": "b1c8536a9833761bbf7d810752aa7483730947b5bf693eadc6a25410f8361716",
    "unsigned_u32_branch_is_exact": "726e376e0414ee9bd59d88996875eb445baa54e1375775cc0cf057f066c1403c",
    "unsigned_u64_branch_is_exact": "82ac0ae89a61f23febd3ffac4da680aadc4a848f1c2fd4b94f6dd9f3fe50a76f",
    "float_f32_branch_is_exact": "62fd594119324ba1d97cfe9611a47994494cc2745cebc407901152da8ed879f1",
    "float_f64_branch_is_exact": "8adef5f984cde66a496b0c2f487270492f5dc19533271c190138e650fc0ea06f",
    "bool_branch_is_exact": "7fd07bd83bae1e877d140de2e09bb75f87aa6824e5c27c3f5f241c8eeaf360f6",
}
REJECTED = {
    "unknown_kind_declines": "513c2954b7b1b96ba5064364c48a476afdd0aa00082c67bc0e6e4ebdc071b5ad",
    "unsupported_signed_width_declines": "fbf5b4b31ebc352be16a81b2002989566f51e5c684fe70d2feb70f405657e69b",
    "unsupported_unsigned_width_declines": "79caa9a8f0aa69b998005351b55583f8015d2b5dd791debeaa010a0d0e97993c",
    "unsupported_float_width_declines": "65772edd2aa5e899e690fc9a002bcdf78781e7a56b362d3ea92442c035eedfe6",
}
CASES = [
    ("signed_i8_branch_is_exact", 'TypeKind.Signed', 8, '"i8"', 1),
    ("signed_i16_branch_is_exact", 'TypeKind.Signed', 16, '"i16"', 2),
    ("signed_i32_branch_is_exact", 'TypeKind.Signed', 32, '"i32"', 3),
    ("signed_i64_branch_is_exact", 'TypeKind.Signed', 64, '"i64"', 4),
    ("unsigned_u8_branch_is_exact", 'TypeKind.Unsigned', 8, '"u8"', 5),
    ("unsigned_u16_branch_is_exact", 'TypeKind.Unsigned', 16, '"u16"', 6),
    ("unsigned_u32_branch_is_exact", 'TypeKind.Unsigned', 32, '"u32"', 7),
    ("unsigned_u64_branch_is_exact", 'TypeKind.Unsigned', 64, '"u64"', 8),
    ("float_f32_branch_is_exact", 'TypeKind.Float', 32, '"f32"', 9),
    ("float_f64_branch_is_exact", 'TypeKind.Float', 64, '"f64"', 10),
    ("bool_branch_is_exact", 'TypeKind.Bool', None, '"bool"', 11),
]
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", text)
    if not match: raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
proof_text = POSITIVE.read_text()
for name, digest in EXPECTED.items():
    if hashlib.sha256(compact(section(proof_text, name)).encode()).hexdigest() != digest:
        raise SystemExit(f"{name} proof changed since source binding")
rejected_text = NEGATIVE.read_text()
for name, digest in REJECTED.items():
    if hashlib.sha256(compact(section(rejected_text, name)).encode()).hexdigest() != digest:
        raise SystemExit(f"{name} proof changed since source binding")
body = compact(section(SOURCE.read_text(), "stage0_scalar_type_name"))
for _, kind, bits, spelling, _ in CASES:
    check = f"value_type.kind=={kind}"
    if check not in body: raise SystemExit(f"missing production kind branch {kind}")
    expected = f"return{spelling}ifvalue_type.bits=={bits}" if bits is not None else f"return{spelling}ifvalue_type.kind=={kind}"
    if expected not in body: raise SystemExit(f"missing production spelling branch {spelling}")
if not body.endswith('return""'):
    raise SystemExit("unsupported scalar types must still decline with an empty spelling")
if args.source_only:
    print(f"source_bound=True positive={len(CASES)} rejected_cases={len(REJECTED)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict": raise SystemExit("scalar mangle proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
result = subprocess.run([str(BIN), "--json", str(POSITIVE)], capture_output=True, text=True, timeout=60)
report = json.loads(result.stdout)
rejected = subprocess.run([str(BIN), "--json", str(NEGATIVE)], capture_output=True, text=True, timeout=60)
rejected_report = json.loads(rejected.stdout)
if result.returncode or report.get("status") != "proved" or report.get("summary", {}).get("proven") != report.get("summary", {}).get("obligations") or report.get("replay", {}).get("gaps") != 0 or rejected.returncode or rejected_report.get("status") != "proved" or rejected_report.get("summary", {}).get("proven") != rejected_report.get("summary", {}).get("obligations") or rejected_report.get("replay", {}).get("gaps") != 0:
    raise SystemExit("scalar mangle branch proofs did not fully replay")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("scalar mangle proof inputs changed during replay")
print(json.dumps({"proved": report["summary"]["proven"] + rejected_report["summary"]["proven"], "source_bound": True, "replay_gaps": 0}))
