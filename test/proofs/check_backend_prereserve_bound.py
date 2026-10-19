"""Bind counted-loop reserve arithmetic proofs to the backend trip/push caps."""
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
SOURCE = ROOT / 'src/backend/codegen_loop_prereserve.elisa'
POSITIVE = HERE / 'backend_prereserve_bound.elisa'
NEGATIVE = HERE / 'backend_prereserve_bound_rejected.elisa'
POSITIVE_HASHES = {
    'prereserve_trip_cap_model': 'afcd4c2f748154956cadf52a9eabc70bc2444d7a2a148f0a0899179a6ff377e2',
    'prereserve_single_i64_trip_cap': '5960c4ff4be0028bd2a4b56177ac4c2d54d76db9918c17b1d405d6313e0a59e4',
    'prereserve_two_i64_trip_cap': '4b907ed7ca25b01635f05f3021e3545824dde8818234066852b9e92dcabd4e32',
    'prereserve_zero_stride_reserves_nothing': '57672b8e9f84f2c94011af4a29b01b80de8f57089d80f72fa2ecab0705a1bd26',
    'prereserve_too_many_pushes_disable_reservation': 'e08391e6bc916e8b5ff46b9ce80f37df6584843b588f1297134b1ea69033b3a5',
    'prereserve_extra_capacity_is_i64_safe': '62c3192ef0e1beaa4e6943a9f9e0b4dd21f97ea9ee3810099423048a08ab9d06',
    'prereserve_negative_bound_reserves_nothing': 'd7a9cd043d645aa0689cc71f95e661171189868f339c479eb3b04b1479839129',
    'prereserve_over_cap_bound_is_clamped': 'b703f93f541f741cd212510a8ca97f52c83aa164c0f951874f5f3003a15c8d5f',
    'prereserve_in_range_bound_is_preserved': '89b259582060057985b8f7083fca05e3772251f319696858efc8298f800187b5',
    'prereserve_zero_bound_reserves_nothing': 'c39a0c706ad4038871ca7f2ebed6677b8ed60dde769a3ffebed487c4071098d0',
}
NEGATIVE_HASHES = {
    'false_old_trip_push_stride_product_exceeds_byte_budget': '7a74a0be937f716a92cec42a0347b55997c6159732c1322cf3206ff768c316f0',
    'false_over_cap_bound_is_not_clamped': 'efee155fa79671af30c0d0f87661cbda1fe5bc919c1f6cfa61401de2b1960511',
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
if not NEGATIVE.read_text().startswith('include "./backend_prereserve_bound.elisa"'):
    raise SystemExit('false controls must import the positive reserve model')
source = compact(SOURCE.read_text())
for fragment in (
    'constmoduleLoopPrereserveLimits:MAX_RESERVED_BYTES:u64=67108864',
    'MAX_PUSHES_PER_ITERATION:i64=64',
    'skip<-trueifpushes<=0orpushes>LoopPrereserveLimits::MAX_PUSHES_PER_ITERATION',
    'defprereserve_trip_cap(pushes:i64,element_stride_bytes:u64)->u64:',
    'return0ifpushes<=0orpushes>LoopPrereserveLimits::MAX_PUSHES_PER_ITERATIONorelement_stride_bytes==0',
    'returnLoopPrereserveLimits::MAX_RESERVED_BYTES/element_stride_bytes/pushes.u64()',
    'pushes:i64=prereserve_push_count(body,receiver,push_count_budget)',
    'element_stride_bytes:u64=LLVMABISizeOfType(structs.target.target_data,element_llvm_type)',
    'trip_cap<-prereserve_trip_cap(pushes,element_stride_bytes)',
    'LLVMBuildICmp(builder,38,wide,zero,"prereserve.positive")',
    'LLVMBuildSelect(builder,LLVMBuildICmp(builder,36,wide,cap,"prereserve.under.cap"),wide,cap,"prereserve.capped")',
    'LLVMBuildSelect(builder,positive,capped,zero,"prereserve.trips")',
    'emit_checked_reserve_binary(trips,LLVMConstInt(i64_type,pushes.u64(),0),true',
):
    if fragment not in source:
        raise SystemExit(f'backend reserve arithmetic changed: {fragment}')
if args.source_only:
    print(f'source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}')
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get('compile_mode') != 'strict':
    raise SystemExit('pre-reserve proof requires strict Elisa-Proof build')
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + '.manifest.json'), BIN.with_name(BIN.name + '.manifest.json.sha256'), PROVER / 'ELISA_COMPILER_REV', Path(__file__), HERE / 'proof_product_gate.py', SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), '--json', str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get('status') != 'proved' or positive.get('summary', {}).get('proven') != positive.get('summary', {}).get('obligations') or positive.get('summary', {}).get('semantic_diagnostics'):
    raise SystemExit('pre-reserve arithmetic obligations did not fully prove cleanly')
code, negative = run(NEGATIVE)
if code != 1 or negative.get('status') != 'failed' or {finding.get('name') for finding in negative.get('findings', [])} != set(NEGATIVE_HASHES) or not all(finding.get('kind') == 'ensure-unproven' and finding.get('status') in ('unknown', 'disproved') for finding in negative.get('findings', [])):
    raise SystemExit('pre-reserve arithmetic false controls were not rejected')
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit('pre-reserve proof inputs changed during replay')
print(json.dumps({'proved': positive['summary']['proven'], 'false_controls_rejected': len(NEGATIVE_HASHES), 'source_bound': True}))
