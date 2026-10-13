"""Source-bind EASM checked signed add/sub accepted-branch proofs."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure
parser=argparse.ArgumentParser(); parser.add_argument('--source-only',action='store_true'); args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
PROVER=Path(os.environ.get('ELISA_PROOF_ROOT',ROOT.parent/'elisa-proof')).resolve(strict=not args.source_only)
BIN=Path(os.environ.get('ELISA_PROOF_BIN',PROVER/'build/elisa-proof')).resolve(strict=not args.source_only)
SOURCE=ROOT/'src/backend/easm_verify_memory.elisa'; PROOF=HERE/'easm_checked_add_sub.elisa'; NEGATIVE=HERE/'easm_checked_add_sub_rejected.elisa'
NEGATIVE_NAMES={'false_positive_add_overflow_is_accepted','false_negative_add_overflow_is_accepted','false_positive_sub_overflow_is_accepted','false_negative_sub_overflow_is_accepted'}
NEGATIVE_HASHES={'false_positive_add_overflow_is_accepted':'776d5839c9362ff012af93228c19d16e928250f5f01aa6c9ed478ebacfa227f9','false_negative_add_overflow_is_accepted':'bfbc4c1b111d28ed51eab88cc9df5a0fea189e7bad674a1433019d8d678ed06d','false_positive_sub_overflow_is_accepted':'ab487514b2680f6c8ee8a2cba00a77a5eb8fdc69d58130b5c79416e4f6344f76','false_negative_sub_overflow_is_accepted':'f5ca5708d8fa94ef71cf77d6ada63ed9347db6bec070347296ef106387d0e35c'}
HASHES={'safe_positive_add':'9b54bc85308b68c7fad1788c987e8dc810ed8e5ec4b1faa01ccf77d8cf8dac93','safe_negative_add':'7384ac0d848e112c85a5a78f5a356d99302a03e4e0a00bc441d69a39a519c905','safe_positive_sub':'253653eb49128ba6ea938618889a7d0cccfbb8df5f97ac0fbdb835c28220aff0','safe_negative_sub':'9fb907dccb57a275f96566e1e9c09c4d88bcb3b157a30df7274d13beb7f22415'}
def compact(s:str)->str:return ''.join(''.join(line.split('#',1)[0].split()) for line in s.splitlines())
def section(s:str,name:str)->str:
 ms=list(re.finditer(rf'(?m)^([ \t]*)def {re.escape(name)}\(',s))
 if len(ms)!=1:raise SystemExit(f'expected one {name} declaration')
 m=ms[0]; indent=m.group(1); nxt=re.search(rf'(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(',s[m.end():])
 return s[m.start():m.end()+nxt.start() if nxt else len(s)]
src=SOURCE.read_text()
for fname,frags in [('easm_i64_add_checked',('ifright>0andleft>EASM_I64_MAX-right','ifright<0andleft<EASM_I64_MIN-right','return(true,left+right)'),),('easm_i64_sub_checked',('ifright>0andleft<EASM_I64_MIN+right','ifright<0andleft>EASM_I64_MAX+right','return(true,left-right)'))]:
 body=compact(section(src,fname)); positions=[]
 for f in frags:
  if f not in body:raise SystemExit(f'{fname} lost checked arithmetic guard: {f}')
  positions.append(body.index(f))
 if positions!=sorted(positions):raise SystemExit(f'{fname} must reject overflow before arithmetic')
proof=PROOF.read_text()
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',proof))!=set(HASHES):raise SystemExit('EASM checked add/sub proof inventory changed')
for name,digest in HASHES.items():
 if hashlib.sha256(compact(section(proof,name)).encode()).hexdigest()!=digest:raise SystemExit(f'{name} changed since source binding')
negative=NEGATIVE.read_text()
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',negative))!=NEGATIVE_NAMES:raise SystemExit('EASM overflow false-control inventory changed')
if not negative.startswith('include \"./easm_checked_add_sub.elisa\"'):raise SystemExit('EASM false controls must include the branch model')
for name,digest in NEGATIVE_HASHES.items():
 if hashlib.sha256(compact(section(negative,name)).encode()).hexdigest()!=digest:raise SystemExit(f'{name} changed since false-control binding')
if args.source_only:print(json.dumps({'source_bound':True,'proved_branches':len(HASHES),'false_controls':len(NEGATIVE_NAMES)}));raise SystemExit(0)
product=require_current_product(BIN,PROVER)
if product.get('compile_mode')!='strict':raise SystemExit('EASM arithmetic proof requires strict Elisa-Proof build')
inputs=list(dict.fromkeys([BIN,BIN.with_name(BIN.name+'.manifest.json'),BIN.with_name(BIN.name+'.manifest.json.sha256'),PROVER/'ELISA_COMPILER_REV',Path(__file__),HERE/'proof_product_gate.py',SOURCE,PROOF,NEGATIVE,*source_include_closure([PROOF,NEGATIVE])]))
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
p=subprocess.run([str(BIN),'--json',str(PROOF)],capture_output=True,text=True,timeout=60); report=json.loads(p.stdout)
if p.returncode or report.get('status')!='proved' or report.get('summary',{}).get('proven')!=report.get('summary',{}).get('obligations'):raise SystemExit('EASM checked arithmetic branch obligations were not all proved')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('EASM proof inputs changed during replay')
q=subprocess.run([str(BIN),'--json',str(NEGATIVE)],capture_output=True,text=True,timeout=60); rejected=json.loads(q.stdout)
if q.returncode!=1 or rejected.get('status')!='failed' or {r.get('name') for r in rejected.get('findings',[])}!=NEGATIVE_NAMES or not all(r.get('kind')=='ensure-unproven' and r.get('status') in ('unknown','disproved') for r in rejected.get('findings',[])):raise SystemExit('EASM false overflow claims were not rejected')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('EASM inputs changed during false-control replay')
print(json.dumps({'proved':report['summary']['proven'],'false_controls_rejected':len(NEGATIVE_NAMES),'source_bound':True}))
