"""Bind EASM's unknown/missing/exact layout-width policy to proof obligations."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure
parser=argparse.ArgumentParser(); parser.add_argument('--source-only',action='store_true'); args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
PROVER=Path(os.environ.get('ELISA_PROOF_ROOT',ROOT.parent/'elisa-proof')).resolve(strict=not args.source_only)
BIN=Path(os.environ.get('ELISA_PROOF_BIN',PROVER/'build/elisa-proof')).resolve(strict=not args.source_only)
SOURCE=ROOT/'src/backend/easm_verify_provenance.elisa'; PROOF=HERE/'easm_layout_access_width.elisa'; NEGATIVE=HERE/'easm_layout_access_width_rejected.elisa'
NEGATIVE_NAME='false_mismatched_positive_width_allows_access'
NEGATIVE_HASH='5f3be169e0dac9c3844a49282ef683e92a30d77bf9df8a1b4cf1623147cf2f62'
HASHES={'layout_access_width_is_valid':'6ccb43475c2474bb9c1da2bffcd3f9160edd3a7abbd1a0950c3077bbf780f8db','unknown_layout_width_allows_access':'4f5a19de044f20aa51379f1f5aa78bcb627a5efc71028cae64d209795483f5b5','missing_layout_width_rejects_access':'9b5e82ee71050dfe6e466d731a6da436b6551b64c6d9d4fadb1d0b8235bf91a5','matching_layout_width_allows_access':'70b31091556bcdd3cee8a72c9bb972fb05c3269c6b3d99e3e2160a175205cc36','four_byte_field_rejects_eight_byte_access':'3192d9399562266008884f1e426f70aa7c1d19b2688208f8e477355555c7f21f','eight_byte_field_rejects_four_byte_access':'264054c1a9f40e369ee65d1853cfc94ffe848f3ea0a7dc1ae81d29f89861e470'}
def compact(s:str)->str:return ''.join(''.join(line.split('#',1)[0].split()) for line in s.splitlines())
def section(s:str,name:str)->str:
 ms=list(re.finditer(rf'(?m)^([ \t]*)def {re.escape(name)}\(',s))
 if len(ms)!=1:raise SystemExit(f'expected one {name} declaration')
 m=ms[0]; indent=m.group(1); nxt=re.search(rf'(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(',s[m.end():])
 return s[m.start():m.end()+nxt.start() if nxt else len(s)]
body=compact(section(SOURCE.read_text(),'layout_access_is_valid'))
for fragment in ('declared_width:i64=layout_field_width(layout,field_name)','ifdeclared_width<0:returnfalse','returndeclared_width==0ordeclared_width==access_width'):
 if fragment not in body:raise SystemExit(f'EASM layout access width policy changed: {fragment}')
proof=PROOF.read_text()
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',proof))!=set(HASHES):raise SystemExit('layout access width proof inventory changed')
for name,digest in HASHES.items():
 if hashlib.sha256(compact(section(proof,name)).encode()).hexdigest()!=digest:raise SystemExit(f'{name} changed since source binding')
negative=NEGATIVE.read_text()
if set(re.findall(r'(?m)^def ([A-Za-z_]\w*)\(',negative))!={NEGATIVE_NAME}:raise SystemExit('layout-width false-control inventory changed')
if not negative.startswith('include \"./easm_layout_access_width.elisa\"'):raise SystemExit('layout-width false control must include the positive model')
if hashlib.sha256(compact(section(negative,NEGATIVE_NAME)).encode()).hexdigest()!=NEGATIVE_HASH:raise SystemExit('layout-width false control changed since source binding')
if args.source_only:print(json.dumps({'source_bound':True,'theorems':len(HASHES),'false_controls':1}));raise SystemExit(0)
product=require_current_product(BIN,PROVER)
if product.get('compile_mode')!='strict':raise SystemExit('EASM width proof requires strict Elisa-Proof build')
inputs=list(dict.fromkeys([BIN,BIN.with_name(BIN.name+'.manifest.json'),BIN.with_name(BIN.name+'.manifest.json.sha256'),PROVER/'ELISA_COMPILER_REV',Path(__file__),HERE/'proof_product_gate.py',SOURCE,PROOF,NEGATIVE,*source_include_closure([PROOF,NEGATIVE])]))
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
p=subprocess.run([str(BIN),'--json',str(PROOF)],capture_output=True,text=True,timeout=60); report=json.loads(p.stdout)
if p.returncode or report.get('status')!='proved' or report.get('summary',{}).get('proven')!=report.get('summary',{}).get('obligations'):raise SystemExit('layout access width obligations were not all proved')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('EASM width proof inputs changed during replay')
q=subprocess.run([str(BIN),'--json',str(NEGATIVE)],capture_output=True,text=True,timeout=60); rejected=json.loads(q.stdout)
if q.returncode!=1 or rejected.get('status')!='failed' or {f.get('name') for f in rejected.get('findings',[])}!={NEGATIVE_NAME} or not all(f.get('kind')=='ensure-unproven' and f.get('status') in ('unknown','disproved') for f in rejected.get('findings',[])):raise SystemExit('mismatched-width false control was not rejected')
if {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}!=before:raise SystemExit('EASM inputs changed during false-control replay')
print(json.dumps({'proved':report['summary']['proven'],'false_controls_rejected':1,'source_bound':True}))
