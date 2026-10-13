"""Bind 32-bit reserve addition range proofs to backend overflow checks."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument('--source-only', action='store_true')
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get('ELISA_PROOF_ROOT', ROOT.parent / 'elisa-proof')).resolve(strict=not args.source_only)
BIN = Path(os.environ.get('ELISA_PROOF_BIN', PROVER / 'build/elisa-proof')).resolve(strict=not args.source_only)
SOURCE = ROOT / 'src/backend/codegen_container_ops.elisa'
POSITIVE = HERE / 'backend_reserve_u32_add.elisa'
NEGATIVE = HERE / 'backend_reserve_u32_add_rejected.elisa'
POSITIVE_HASHES = {
    'reserve_u32_add_operands_bound_the_wide_sum': 'b7f02ef8241bfcafce833fbe523a6b86118bfca9606c2268dc135e659fa7eb91',
    'reserve_u32_add_accepted_result_fits_target': 'a182c8c2c79e0486c56914d865435b3914109458af0ea0317a73a0ec840d7c18',
}
NEGATIVE_HASHES = {
    'false_maximum_u32_operands_sum_fits_target': '7d0e0d09e4935cbad41a45c21b99df77dbbc5416e52a063e0058bdeabe5b241c',
}
def compact(text: str) -> str:
    return ''.join(''.join(line.split('#', 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf'(?m)^[ \t]*def {re.escape(name)}\(', text)
    if not match:
        raise SystemExit(f'missing {name}')
    following = re.search(r'(?m)^[ \t]*def [A-Za-z_]\w*\(', text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
for path, expected in ((POSITIVE, POSITIVE_HASHES), (NEGATIVE, NEGATIVE_HASHES)):
    text = path.read_text()
    for name, digest in expected.items():
        if hashlib.sha256(compact(section(text, name)).encode()).hexdigest() != digest:
            raise SystemExit(f'{name} proof changed since source binding')
if not NEGATIVE.read_text().startswith('include "./backend_reserve_u32_add.elisa"'):
    raise SystemExit('false control must import the target-width addition model')
source_text = SOURCE.read_text()
if 'constDARRAY_U32_MAX:u64=4294967295' not in compact(source_text):
    raise SystemExit('reserve target-width maximum changed')
match = re.search(r'(?m)^([ \t]*)def emit_overflow_binary\(', source_text)
if not match:
    raise SystemExit('missing emit_overflow_binary')
next_function = re.search(rf'(?m)^{re.escape(match.group(1))}def [A-Za-z_]\w*\(', source_text[match.end():])
source = compact(source_text[match.start():match.end() + next_function.start() if next_function else len(source_text)])
for fragment in (
    'ifmultiplyandtarget_bits==32:',
    'intrinsic_name:sview="llvm.umul.with.overflow"ifmultiplyelse"llvm.uadd.with.overflow"',
    'iftarget_bits==32:',
    'left_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,left,LLVMConstInt(int_type,DARRAY_U32_MAX,0)',
    'right_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,right,LLVMConstInt(int_type,DARRAY_U32_MAX,0)',
    'value_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,value,LLVMConstInt(int_type,DARRAY_U32_MAX,0)',
    'target_overflow:mutableLLVMValueRef=LLVMBuildOr(builder,left_exceeds,right_exceeds',
    'target_overflow<-LLVMBuildOr(builder,target_overflow,value_exceeds',
):
    if fragment not in source:
        raise SystemExit(f'backend 32-bit reserve overflow checks changed: {fragment}')
if args.source_only:
    print(f'source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}')
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get('compile_mode') != 'strict':
    raise SystemExit('32-bit reserve addition proof requires strict Elisa-Proof build')
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + '.manifest.json'), BIN.with_name(BIN.name + '.manifest.json.sha256'), PROVER / 'ELISA_COMPILER_REV', Path(__file__), HERE / 'proof_product_gate.py', SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), '--json', str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get('status') != 'proved' or positive.get('summary', {}).get('proven') != positive.get('summary', {}).get('obligations') or positive.get('summary', {}).get('semantic_diagnostics'):
    raise SystemExit('32-bit reserve addition obligations did not fully prove cleanly')
code, negative = run(NEGATIVE)
if code != 1 or negative.get('status') != 'failed' or {finding.get('name') for finding in negative.get('findings', [])} != set(NEGATIVE_HASHES) or not all(finding.get('kind') == 'ensure-unproven' and finding.get('status') in ('unknown', 'disproved') for finding in negative.get('findings', [])):
    raise SystemExit('32-bit reserve addition false control was not rejected')
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit('32-bit reserve addition inputs changed during replay')
print(json.dumps({'proved': positive['summary']['proven'], 'false_controls_rejected': len(NEGATIVE_HASHES), 'source_bound': True}))
