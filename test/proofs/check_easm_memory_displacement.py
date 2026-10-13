"""Bind EASM memory-displacement fail-closed parsing to its production path."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure
parser=argparse.ArgumentParser(); parser.add_argument('--source-only',action='store_true'); args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
PROVER=Path(os.environ.get('ELISA_PROOF_ROOT',ROOT.parent/'elisa-proof')).resolve(strict=not args.source_only)
BIN=Path(os.environ.get('ELISA_PROOF_BIN',PROVER/'build/elisa-proof')).resolve(strict=not args.source_only)
MEMORY=ROOT/'src/backend/easm_verify_memory.elisa'; PARSER=ROOT/'src/backend/easm_verify_function.elisa'; PROOF=HERE/'easm_memory_displacement.elisa'
HASHES={'memory_displacement_result':'c99cc50dacfd2bb8757316436a5ac9d1997b93746c9bf56280ca5637dd97c614','invalid_displacement_compatibility_value_is_zero':'3cd82cb837ce6d7dae07f2d6864ec26434ab2a04d124d04c88b2a74ddd29f5ab'}
def compact(s:str)->str:return ''.join(''.join(line.split('#',1)[0].split()) for line in s.splitlines())
def section(s:str,name:str)->str:
 ms=list(re.finditer(rf'(?m)^([ \t]*)def {re.escape(name)}\(',s))
 if len(ms)!=1:raise SystemExit(f'expected one {name} declaration')
 m=ms[0]; indent=m.group(1); nxt=re.search(rf'(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(',s[m.end():])
 return s[m.start():m.end()+nxt.start() if nxt else len(s)]
body=compact(section(MEMORY.read_text(),'easm_memory_displacement_checked'))
ordered=('open:usize=easm_find(operand,"(")','ifopen>=operand.len:return(true,0)','prefix:sview=easm_trim(operand[0:open])','ifprefix.len==0:return(true,0)','returneasm_parse_i64_checked(prefix)')
if any(x not in body for x in ordered) or [body.index(x) for x in ordered]!=sorted(body.index(x) for x in ordered):raise SystemExit('EASM displacement parser changed its fail-closed branch order')
parse=compact(section(PARSER.read_text(),'easm_parse_i64_checked'))
if 'ensurenotresult.validimpliesresult.value==0' not in parse:raise SystemExit('checked decimal parser must return zero for invalid parses')
wrapper=compact(section(MEMORY.read_text(),'easm_memory_displacement'))
if 'parsed:(valid:bool,value:i64)=easm_memory_displacement_checked(operand)' not in wrapper or 'returnparsed.valueifparsed.validelse0' not in wrapper:raise SystemExit('legacy displacement wrapper changed its fail-closed projection')
proof=PROOF.read_text()
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',proof))!=set(HASHES):raise SystemExit('displacement proof inventory changed')
for name,digest in HASHES.items():
 if hashlib.sha256(compact(section(proof,name)).encode()).hexdigest()!=digest:raise SystemExit(f'{name} changed since source binding')
if args.source_only:print(json.dumps({'source_bound':True,'theorems':len(HASHES)}));raise SystemExit(0)
product=require_current_product(BIN,PROVER)
if product.get('compile_mode')!='strict':raise SystemExit('EASM displacement proof requires strict Elisa-Proof build')
inputs=list(dict.fromkeys([BIN,BIN.with_name(BIN.name+'.manifest.json'),BIN.with_name(BIN.name+'.manifest.json.sha256'),PROVER/'ELISA_COMPILER_REV',Path(__file__),HERE/'proof_product_gate.py',MEMORY,PARSER,PROOF,*source_include_closure([PROOF])]))
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
p=subprocess.run([str(BIN),'--json',str(PROOF)],capture_output=True,text=True,timeout=60); report=json.loads(p.stdout)
if p.returncode or report.get('status')!='proved' or report.get('summary',{}).get('proven')!=report.get('summary',{}).get('obligations'):raise SystemExit('displacement fail-closed obligation was not proved')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('EASM displacement proof inputs changed during replay')
print(json.dumps({'proved':report['summary']['proven'],'source_bound':True}))
