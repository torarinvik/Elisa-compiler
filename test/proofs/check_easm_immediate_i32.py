"""Bind signed-32-bit EASM immediate range proofs to the parser guard."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure
parser=argparse.ArgumentParser(); parser.add_argument('--source-only',action='store_true'); args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
PROVER=Path(os.environ.get('ELISA_PROOF_ROOT',ROOT.parent/'elisa-proof')).resolve(strict=not args.source_only)
BIN=Path(os.environ.get('ELISA_PROOF_BIN',PROVER/'build/elisa-proof')).resolve(strict=not args.source_only)
SOURCE=ROOT/'src/backend/easm_verify_memory.elisa'; PROOF=HERE/'easm_immediate_i32.elisa'; NEGATIVE=HERE/'easm_immediate_i32_rejected.elisa'
POSITIVE_HASHES={'immediate_checked_result':'920e1ebda23bc2a4b0f18bee025264754ca4ff0ed41638a2525fea2808c59468','valid_immediate_compatibility_value_preserves_parse':'c0dda5911adb93274a426b3a60b7bd8222880f5afa2e469c094a50acd03a03f8','invalid_immediate_compatibility_value_is_zero':'e62f5feee13dff0711e21a067e2eff57a8545e47f4657c13a43bac437438c96a','immediate_min_i32_is_accepted':'8fdd68dd679f1a4c4da6f81e94c4091c24f18e7f1a4b07755608eaeb70159adf','immediate_max_i32_is_accepted':'6dac16ea80d640cd9a1c9e4f7bb8623e97f6f8d3dd11622eaed2f9872f4bb120'}
NEGATIVE_HASHES={'false_invalid_immediate_compatibility_value_is_nonzero':'c1edc61a5fd5d9e03ea40a26ff24767fb5cb068bc9705fa00f4ceedcb7ecdd85','false_below_i32_immediate_is_accepted':'a2aaff1152d135d67b31b857a6140949be70a022052c988b902c03b1187b5825','false_above_i32_immediate_is_accepted':'b7b1cb49df3efa03c7333290defc00beae31a545ce0daddf1b6a18b5390fe4e8'}
def compact(s:str)->str:return ''.join(''.join(line.split('#',1)[0].split()) for line in s.splitlines())
def section(s:str,name:str)->str:
 ms=list(re.finditer(rf'(?m)^([ \t]*)def {re.escape(name)}\(',s))
 if len(ms)!=1:raise SystemExit(f'expected one {name} declaration')
 m=ms[0]; indent=m.group(1); nxt=re.search(rf'(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(',s[m.end():])
 return s[m.start():m.end()+nxt.start() if nxt else len(s)]
body=compact(section(SOURCE.read_text(),'easm_immediate_operand_after_dollar_checked'))
ordered=('dollar:usize=easm_find(operand,"$")','ifdollar>=operand.len:return(false,0)','parsed:(valid:bool,value:i64)=easm_parse_i64_checked(easm_trim(operand[dollar+1.usize():operand.len]))','return(false,0)ifnotparsed.validorparsed.value<-2147483648orparsed.value>2147483647','returnparsed')
if any(x not in body for x in ordered) or [body.index(x) for x in ordered]!=sorted(body.index(x) for x in ordered):raise SystemExit('EASM immediate parser changed parse/range/return order')
wrapper=compact(section(SOURCE.read_text(),'easm_immediate_after_dollar'))
if 'parsed:(valid:bool,value:i64)=easm_immediate_after_dollar_checked(text)' not in wrapper or 'returnparsed.valueifparsed.validelse0' not in wrapper:raise SystemExit('legacy immediate wrapper changed its checked-value projection')
for path,expected in ((PROOF,POSITIVE_HASHES),(NEGATIVE,NEGATIVE_HASHES)):
 source=path.read_text()
 if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',source))!=set(expected):raise SystemExit(f'{path.name} proof inventory changed')
 for name,digest in expected.items():
  if hashlib.sha256(compact(section(source,name)).encode()).hexdigest()!=digest:raise SystemExit(f'{name} changed since source binding')
if not NEGATIVE.read_text().startswith('include "./easm_immediate_i32.elisa"'):raise SystemExit('immediate false controls must include positive policy model')
if args.source_only:print(json.dumps({'source_bound':True,'positive':len(POSITIVE_HASHES),'false_controls':len(NEGATIVE_HASHES)}));raise SystemExit(0)
product=require_current_product(BIN,PROVER)
if product.get('compile_mode')!='strict':raise SystemExit('EASM immediate proof requires strict Elisa-Proof build')
inputs=list(dict.fromkeys([BIN,BIN.with_name(BIN.name+'.manifest.json'),BIN.with_name(BIN.name+'.manifest.json.sha256'),PROVER/'ELISA_COMPILER_REV',Path(__file__),HERE/'proof_product_gate.py',SOURCE,PROOF,NEGATIVE,*source_include_closure([PROOF,NEGATIVE])]))
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
def run(path:Path):
 p=subprocess.run([str(BIN),'--json',str(path)],capture_output=True,text=True,timeout=60);return p.returncode,json.loads(p.stdout)
code,positive=run(PROOF)
if code or positive.get('status')!='proved' or positive.get('summary',{}).get('proven')!=positive.get('summary',{}).get('obligations'):raise SystemExit('immediate boundary obligations were not all proved')
code,negative=run(NEGATIVE)
if code!=1 or negative.get('status')!='failed' or {f.get('name') for f in negative.get('findings',[])}!=set(NEGATIVE_HASHES) or not all(f.get('kind')=='ensure-unproven' and f.get('status') in ('unknown','disproved') for f in negative.get('findings',[])):raise SystemExit('out-of-range immediate controls were not rejected')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('EASM immediate proof inputs changed during replay')
print(json.dumps({'proved':positive['summary']['proven'],'false_controls_rejected':len(NEGATIVE_HASHES),'source_bound':True}))
