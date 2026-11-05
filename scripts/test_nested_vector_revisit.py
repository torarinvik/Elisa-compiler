#!/usr/bin/env python3
"""Check bounded eligibility for a late nested-vector optimization revisit."""
import os,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CONFIG=os.environ.get('LLVM_CONFIG','/opt/homebrew/opt/llvm@23/bin/llvm-config')
def run(c):return subprocess.run(list(map(str,c)),capture_output=True,text=True,check=True,timeout=28)
def flags(*a):return shlex.split(run([CONFIG,*a]).stdout)
DRIVER='''#include <llvm/IRReader/IRReader.h>\n#include <llvm/Support/SourceMgr.h>\n#include "llvm_validation_peel.cpp"\nint main(int n,char**v){llvm::LLVMContext c;llvm::SMDiagnostic e;auto m=llvm::parseIRFile(v[1],e,c);if(!m){e.print(v[0],llvm::errs());return 2;}llvm::outs()<<shouldRevisitNestedVectorLoops(*m)<<"\\n";}\n'''
IR='''target triple = "TRIPLE"
define void @f(ptr %p, i64 %n) nounwind {
entry: br label %outer
outer:
 %i = phi i64 [0, %entry], [%next, %outer_latch]
 br label %inner
inner:
 %j = phi i64 [0, %outer], [%jnext, %inner]
 %v = load <2 x i64>, ptr %p, align 8
 %jnext = add i64 %j, 1
 %jc = icmp ult i64 %jnext, %n
 br i1 %jc, label %inner, label %outer_latch
outer_latch:
 %next = add i64 %i, 1
 %ic = icmp ult i64 %next, %n
 br i1 %ic, label %outer, label %exit
exit: ret void
}
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
CASES={'nested_vector':(IR,1),'scalar':(IR.replace('load <2 x i64>','load i64'),0),'non_arm':(IR.replace(os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'),'x86_64-unknown-linux-gnu'),0),'sanitized':(IR.replace('nounwind {','nounwind sanitize_address {'),0),'size_opt':(IR.replace('nounwind {','nounwind optsize {'),0),'five_functions':(IR+'\n'.join('define void @extra%d() { ret void }'%i for i in range(4)),0),'large':(IR.replace('exit: ret void','exit:\n'+''.join(' %%t%d = add i64 %%n, %d\n'%(i,i) for i in range(2001))+' ret void'),0)}
with tempfile.TemporaryDirectory(prefix='nested-vector-') as tmp:
 d=Path(tmp);(d/'driver.cpp').write_text(DRIVER);bindir=Path(run([CONFIG,'--bindir']).stdout.strip())
 run([bindir/'clang++',*flags('--cxxflags'),'-I'+str(ROOT/'src/backend'),d/'driver.cpp',*flags('--ldflags','--libs','--system-libs'),'-Wl,-rpath,'+run([CONFIG,'--libdir']).stdout.strip(),'-o',d/'driver'])
 for name,(ir,expected) in CASES.items():
  (d/'test.ll').write_text(ir);actual=int(run([d/'driver',d/'test.ll']).stdout.strip());assert actual==expected,(name,actual);print('PASS',name)
