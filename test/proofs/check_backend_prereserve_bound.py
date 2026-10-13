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
    'prereserve_extra_capacity_is_i64_safe': '667ca3119954e06b5a9d6c8734159258d2584657c1696f6fc0386c6b865c7263',
    'prereserve_negative_bound_reserves_nothing': '6e4c906e196a21a9483733149b437b965437030d236f7ec92de5de0b17a31616',
    'prereserve_over_cap_bound_is_clamped': '083063dbe1ba3a9d51b2ba5b7c38a795dc415ba8e9be015104b574b0b3ee2801',
    'prereserve_in_range_bound_is_preserved': '79867ccb8b79b95f298118cb0618ae3aa72d24dfc6895af2d3acbb54415064b2',
    'prereserve_zero_bound_reserves_nothing': '5d3bed0e82b7cd688dcca33ad13d043f2032e5a7370389190291aae1b3ed65e6',
}
NEGATIVE_HASHES = {
    'false_prereserve_product_below_actual_maximum': '54034d6e3fc79bc55d113175d713863d614c283a180277870de558600c106114',
    'false_over_cap_bound_is_not_clamped': 'c6773b5944be7e4183e10f2bea2b2fee510a5067a8a0d81cb319a8863b6b7bd8',
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
    'constPRERESERVE_CAP:u64=16777216',
    'constPRERESERVE_MAX_PUSHES:i64=64',
    'skip<-trueifpushes<=0orpushes>PRERESERVE_MAX_PUSHES',
    'pushes:i64=prereserve_push_count(body,receiver,push_count_budget)',
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
