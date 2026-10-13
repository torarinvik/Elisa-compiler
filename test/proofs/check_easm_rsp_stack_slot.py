"""Bind EASM stack-slot fail-closed proof to its production guards."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure
parser=argparse.ArgumentParser(); parser.add_argument('--source-only',action='store_true'); args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
PROVER=Path(os.environ.get('ELISA_PROOF_ROOT',ROOT.parent/'elisa-proof')).resolve(strict=not args.source_only)
BIN=Path(os.environ.get('ELISA_PROOF_BIN',PROVER/'build/elisa-proof')).resolve(strict=not args.source_only)
SOURCE=ROOT/'src/backend/easm_verify_memory.elisa'; PROOF=HERE/'easm_rsp_stack_slot.elisa'; NEGATIVE=HERE/'easm_rsp_stack_slot_rejected.elisa'
NAME='rsp_stack_slot_result'; HASH='66016fb0228dbfde7fa86af1e88610cf94eaa8871bba2be3d4f17b4ec95dcc68'
NEGATIVE_HASHES={'false_unknown_stack_state_is_accepted':'0246ce80784e1e28008ba1ccae3fce6533046aec45690f56e684f1e48c1da071','false_nonmemory_operand_is_accepted':'4c5b4b615af6aac325cc69a23b130bfdcd3ebc6093a5f4ebb7d6480405c1a609','false_non_rsp_base_is_accepted':'fd6e536c1a6b2aebfd451bb68e9e67010e857d5bae42be2579eaddd501c97245','false_indexed_operand_is_accepted':'fb3023065a4fb56513845360a76ab2bda15ecd11e190a5b3eb53c9e1be0a82c4','false_invalid_displacement_is_accepted':'30f39f2fc544ca28236e03864acc2b09dc192a9669088b80e4e792ee3c80f8fe','false_overflowed_stack_offset_is_accepted':'2b8e7bd73e7244b690fd4d3ee373aab7b6eb0b9f45314877f9666178186e734f'}
def compact(s:str)->str:return ''.join(''.join(line.split('#',1)[0].split()) for line in s.splitlines())
def section(s:str,name:str)->str:
 ms=list(re.finditer(rf'(?m)^([ \t]*)def {re.escape(name)}\(',s))
 if len(ms)!=1:raise SystemExit(f'expected one {name} declaration')
 m=ms[0]; indent=m.group(1); nxt=re.search(rf'(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(',s[m.end():])
 return s[m.start():m.end()+nxt.start() if nxt else len(s)]
body=compact(section(SOURCE.read_text(),'easm_rsp_stack_slot'))
for fragment in ('ifnotstack_knownornoteasm_memory_operand(operand)oreasm_memory_base_register(operand)!="rsp"oreasm_memory_index_register(operand)!="":return(false,0)','displacement:(valid:bool,value:i64)=easm_memory_displacement_checked(operand)','returneasm_i64_add_checked(stack_delta,displacement.value)ifdisplacement.validelse(false,0)'):
 if fragment not in body:raise SystemExit(f'EASM stack-slot guard path changed: {fragment}')
proof=PROOF.read_text()
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',proof))!={NAME}:raise SystemExit('stack-slot proof inventory changed')
if hashlib.sha256(compact(section(proof,NAME)).encode()).hexdigest()!=HASH:raise SystemExit('stack-slot theorem changed since source binding')
negative=NEGATIVE.read_text()
if not negative.startswith('include \"./easm_rsp_stack_slot.elisa\"'):raise SystemExit('stack-slot false controls must include the positive result model')
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',negative))!=set(NEGATIVE_HASHES):raise SystemExit('stack-slot false-control inventory changed')
for name,digest in NEGATIVE_HASHES.items():
 if hashlib.sha256(compact(section(negative,name)).encode()).hexdigest()!=digest:raise SystemExit(f'{name} changed since false-control binding')
if args.source_only:print(json.dumps({'source_bound':True,'theorems':1,'false_controls':len(NEGATIVE_HASHES)}));raise SystemExit(0)
product=require_current_product(BIN,PROVER)
if product.get('compile_mode')!='strict':raise SystemExit('EASM stack-slot proof requires strict Elisa-Proof build')
inputs=list(dict.fromkeys([BIN,BIN.with_name(BIN.name+'.manifest.json'),BIN.with_name(BIN.name+'.manifest.json.sha256'),PROVER/'ELISA_COMPILER_REV',Path(__file__),HERE/'proof_product_gate.py',SOURCE,PROOF,NEGATIVE,*source_include_closure([PROOF,NEGATIVE])]))
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
p=subprocess.run([str(BIN),'--json',str(PROOF)],capture_output=True,text=True,timeout=60); report=json.loads(p.stdout)
if p.returncode or report.get('status')!='proved' or report.get('summary',{}).get('proven')!=report.get('summary',{}).get('obligations'):raise SystemExit('stack-slot fail-closed obligation was not proved')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('stack-slot proof inputs changed during replay')
q=subprocess.run([str(BIN),'--json',str(NEGATIVE)],capture_output=True,text=True,timeout=60); rejected=json.loads(q.stdout)
if q.returncode!=1 or rejected.get('status')!='failed' or {f.get('name') for f in rejected.get('findings',[])}!=set(NEGATIVE_HASHES) or not all(f.get('kind')=='ensure-unproven' and f.get('status') in ('unknown','disproved') for f in rejected.get('findings',[])):raise SystemExit('stack-slot false controls were not rejected')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('stack-slot inputs changed during false-control replay')
print(json.dumps({'proved':report['summary']['proven'],'false_controls_rejected':len(NEGATIVE_HASHES),'source_bound':True}))
