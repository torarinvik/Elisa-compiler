#!/usr/bin/env python3
"""Validate split-result error outlining and its conservative exclusions."""
import os, shlex, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')
def run(args):
    return subprocess.run([str(x) for x in args], check=True, text=True, capture_output=True, timeout=28)
def flags(*args): return shlex.split(run([CONFIG,*args]).stdout)
DRIVER = '''#include <llvm/IRReader/IRReader.h>
#include <llvm/Support/SourceMgr.h>
#include <llvm/IR/Verifier.h>
#include "llvm_validation_layout.cpp"
int main(int argc,char **argv) {
 llvm::LLVMContext c; llvm::SMDiagnostic e; auto m=llvm::parseIRFile(argv[1],e,c);
 if (!m) { e.print(argv[0],llvm::errs()); return 2; }
 unsigned count=elisacoreBiasValidationReturns(llvm::wrap(m.get()));
 if (llvm::verifyModule(*m,&llvm::errs())) return 3;
 llvm::outs()<<count<<"\\n"; m->print(llvm::outs(),nullptr);
}
'''
IR = '''target triple = "TRIPLE"
define double @f(ptr %p, i64 %len) {
entry:
 %badlen = icmp ne i64 %len, 2
 %null = icmp eq ptr %p, null
 %bad = select i1 %null, i1 true, i1 %badlen
 br i1 %bad, label %exit, label %check
check:
 %x = load i64, ptr %p
 %qptr = getelementptr i64, ptr %p, i64 1
 %q = load i64, ptr %qptr
 %validx = icmp ult i64 %x, 100
 %validq = icmp ult i64 %q, 2
 %ok = select i1 %validx, i1 %validq, i1 false
 br i1 %ok, label %dispatch, label %exit
dispatch:
 %which = icmp eq i64 %q, 0
 br i1 %which, label %first, label %second
first:
 %a = uitofp i64 %x to double
 %a1 = fmul double %a, 2.0
 br label %exit
second:
 %b = uitofp i64 %x to double
 %b1 = fmul double %b, 3.0
 br label %exit
exit:
 %r = phi double [ -1.0, %entry ], [ -1.0, %check ], [ %a1, %first ], [ %b1, %second ]
 ret double %r
}
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
CASES = {
 'split': (IR,1),
 'different_errors': (IR.replace('[ -1.0, %check ]','[ -2.0, %check ]'),0),
 'volatile_load': (IR.replace('%x = load i64','%x = load volatile i64'),0),
 'sanitized': (IR.replace('i64 %len) {','i64 %len) sanitize_address {'),0),
 'strict_fp': (IR.replace('i64 %len) {','i64 %len) strictfp {'),0),
 'other_arch': (IR.replace(os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'),'x86_64-unknown-linux-gnu'),0),
}
with tempfile.TemporaryDirectory(prefix='validation-outline-') as temp:
 d=Path(temp);(d/'driver.cpp').write_text(DRIVER);bindir=Path(run([CONFIG,'--bindir']).stdout.strip())
 run([bindir/'clang++',*flags('--cxxflags'),'-I'+str(ROOT/'src/backend'),d/'driver.cpp',*flags('--ldflags','--libs','--system-libs'),'-Wl,-rpath,'+run([CONFIG,'--libdir']).stdout.strip(),'-o',d/'driver'])
 for name,(ir,want) in CASES.items():
  (d/'test.ll').write_text(ir);out=run([d/'driver',d/'test.ll']).stdout;got=int(out.splitlines()[0]);assert got==want,(name,got);print('PASS',name)
  if name=='split': (d/'outlined.ll').write_text(out.split('\n',1)[1])
 (d/'main.c').write_text('''#include <stdint.h>\nextern double f(int64_t*,uint64_t);\nint main(void){int64_t a[2];if(f(0,2)!=-1)return 1;for(int x=-1;x<=101;x++)for(int q=-1;q<=2;q++){a[0]=x;a[1]=q;double e=x>=0&&x<100&&q>=0&&q<2?(double)x*(q?3:2):-1;if(f(a,2)!=e||f(a,1)!=-1)return 2;}return 0;}\n''')
 for name,ir in [('original',IR),('outlined',(d/'outlined.ll').read_text())]:
  (d/'run.ll').write_text(ir);run([bindir/'clang','-O2',d/'run.ll',d/'main.c','-o',d/'check']);run([d/'check']);print('PASS linked',name)
