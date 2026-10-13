"""Bind supplementary UTF-8 byte range proofs to the backend encoder."""
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
SOURCE = ROOT / 'src/backend/codegen_literals_decode.elisa'
PROOF = HERE / 'backend_literal_utf8_four_byte.elisa'
NEGATIVE = HERE / 'backend_literal_utf8_four_byte_rejected.elisa'
NEGATIVE_NAMES = {'false_supplementary_lead_byte_accepts_bmp', 'false_utf8_lead_byte_accepts_above_unicode_max'}
NEGATIVE_HASHES = {'false_supplementary_lead_byte_accepts_bmp': 'ff82107cc98794ac82aa33804d3f152048dbf9bc6acd69f7668f3260ad7f41a4', 'false_utf8_lead_byte_accepts_above_unicode_max': '07485d8d42f5c36f16a6215ef3ba4c5d930d4d524e0f21db9380cb80db64572a'}
EXPECTED = {
 'supplementary_utf8_lead_byte_is_valid': '37283cbaa862f21919b6ef0ec8da581726cc4debbcd349edcc4d82513bff8ec8',
 'supplementary_utf8_second_byte_is_continuation': 'cd951366815d19c7d4d509e8cc34b86aaa8d4748ad62745516de8db82deb03a8',
 'supplementary_utf8_third_byte_is_continuation': 'b3206b200bc7f4694ec4f331f6c10f60c2edf42c8edf49aa90cef46f4eae43c4',
 'supplementary_utf8_fourth_byte_is_continuation': 'd18f60116d2f2e5e1158253a394f0b88819a36abd790c5575c490c6a80343110',
}
def compact(s: str) -> str:
 return ''.join(''.join(line.split('#',1)[0].split()) for line in s.splitlines())
def section(s: str, name: str) -> str:
 ms=list(re.finditer(rf'(?m)^([ \t]*)def {re.escape(name)}\(',s))
 if len(ms)!=1: raise SystemExit(f'expected one {name} declaration')
 m=ms[0]; indent=m.group(1); nxt=re.search(rf'(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(',s[m.end():])
 return s[m.start():m.end()+nxt.start() if nxt else len(s)]
source=compact(section(SOURCE.read_text(),'push_utf8'))
for shape in ('codepoint<65536','240+(codepoint/262144)','128+((codepoint/4096)%64)','128+((codepoint/64)%64)','128+(codepoint%64)'):
 if shape not in source: raise SystemExit(f'four-byte UTF-8 emission changed: {shape}')
proof=PROOF.read_text()
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',proof)) != set(EXPECTED): raise SystemExit('UTF-8 proof inventory changed')
for name,digest in EXPECTED.items():
 actual=hashlib.sha256(compact(section(proof,name)).encode()).hexdigest()
 if actual!=digest: raise SystemExit(f'{name} changed since source binding')
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',NEGATIVE.read_text())) != NEGATIVE_NAMES: raise SystemExit('UTF-8 false-control inventory changed')
if not NEGATIVE.read_text().startswith('include \"./backend_literal_utf8_four_byte.elisa\"'): raise SystemExit('UTF-8 false controls must include the positive model')
for name,digest in NEGATIVE_HASHES.items():
 if hashlib.sha256(compact(section(NEGATIVE.read_text(),name)).encode()).hexdigest()!=digest: raise SystemExit(f'{name} changed since false-control binding')
if args.source_only:
 print(json.dumps({'source_bound':True,'theorems':len(EXPECTED),'false_controls':len(NEGATIVE_NAMES)})); raise SystemExit(0)
product=require_current_product(BIN,PROVER)
if product.get('compile_mode')!='strict': raise SystemExit('UTF-8 proof requires strict Elisa-Proof build')
inputs=list(dict.fromkeys([BIN,BIN.with_name(BIN.name+'.manifest.json'),BIN.with_name(BIN.name+'.manifest.json.sha256'),PROVER/'ELISA_COMPILER_REV',Path(__file__),HERE/'proof_product_gate.py',SOURCE,PROOF,NEGATIVE,*source_include_closure([PROOF,NEGATIVE])]))
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
p=subprocess.run([str(BIN),'--json',str(PROOF)],capture_output=True,text=True,timeout=60)
d=json.loads(p.stdout)
if p.returncode or d.get('status')!='proved' or d.get('summary',{}).get('proven')!=d.get('summary',{}).get('obligations'): raise SystemExit('UTF-8 arithmetic obligations were not all proved')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before: raise SystemExit('proof inputs changed during replay')
q=subprocess.run([str(BIN),'--json',str(NEGATIVE)],capture_output=True,text=True,timeout=60)
n=json.loads(q.stdout)
if q.returncode!=1 or n.get('status')!='failed' or {r.get('name') for r in n.get('findings',[])}!=NEGATIVE_NAMES or not all(r.get('kind')=='ensure-unproven' and r.get('status') in ('unknown','disproved') for r in n.get('findings',[])): raise SystemExit('UTF-8 false controls were not rejected')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before: raise SystemExit('proof inputs changed during false-control replay')
print(json.dumps({'proved':d['summary']['proven'],'false_controls_rejected':sorted(NEGATIVE_NAMES),'source_bound':True}))
