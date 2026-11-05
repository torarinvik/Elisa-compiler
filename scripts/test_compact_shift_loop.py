#!/usr/bin/env python3
"""Check when compact shift-recurrence unroll policy is applied."""
import os,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CONFIG=os.environ.get('LLVM_CONFIG','/opt/homebrew/opt/llvm@23/bin/llvm-config')
def run(c):return subprocess.run(list(map(str,c)),capture_output=True,text=True,check=True,timeout=28)
def flags(*a):return shlex.split(run([CONFIG,*a]).stdout)
DRIVER='''#include <llvm/IRReader/IRReader.h>\n#include <llvm/Support/SourceMgr.h>\n#include <llvm/IR/Verifier.h>\n#include <llvm/Analysis/TargetLibraryInfo.h>\n#include <llvm/Analysis/AssumptionCache.h>\n#include "llvm_compact_shift_loop.cpp"\nint main(int n,char**v){llvm::LLVMContext c;llvm::SMDiagnostic e;auto m=llvm::parseIRFile(v[1],e,c);if(!m){e.print(v[0],llvm::errs());return 2;}unsigned x=markCompactShiftLoops(*m);if(llvm::verifyModule(*m,&llvm::errs()))return 3;llvm::outs()<<x<<"\\n";m->print(llvm::outs(),nullptr);}\n'''
IR='''target triple = "TRIPLE"
define i64 @f(i64 %x, i64 %d) nounwind {
entry: br label %head
head:
 %i = phi i64 [0, %entry], [%next, %latch]
 %acc = phi i64 [0, %entry], [%new, %latch]
 %shift = sub i64 31, %i
 %right = lshr i64 %x, %shift
 %left = shl i64 %d, %shift
 %bit = shl i64 1, %shift
 %condition = icmp ule i64 %d, %right
 %term = select i1 %condition, i64 %left, i64 %bit
 %new = add i64 %acc, %term
 br label %latch
latch:
 %next = add nuw i64 %i, 1
 %more = icmp ult i64 %next, 32
 br i1 %more, label %head, label %exit
exit: ret i64 %new
}
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
cases={'fixed_shift':(IR,1),'no_right':(IR.replace('lshr i64 %x, %shift','add i64 %x, %shift'),0),'one_left':(IR.replace('shl i64 1, %shift','add i64 1, %shift'),0),'short':(IR.replace('%next, 32','%next, 8'),0),'non_arm':(IR.replace(os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'),'x86_64-unknown-linux-gnu'),0),'sanitized':(IR.replace('nounwind {','nounwind sanitize_address {'),0),'size_opt':(IR.replace('nounwind {','nounwind optsize {'),0),'existing_policy':(IR.replace('label %head, label %exit','label %head, label %exit, !llvm.loop !0')+'\n!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.unroll.count", i32 2}\n',0)}
with tempfile.TemporaryDirectory(prefix='compact-shift-') as tmp:
 d=Path(tmp);(d/'driver.cpp').write_text(DRIVER);bindir=Path(run([CONFIG,'--bindir']).stdout.strip())
 run([bindir/'clang++',*flags('--cxxflags'),'-I'+str(ROOT/'src/backend'),d/'driver.cpp',*flags('--ldflags','--libs','--system-libs'),'-Wl,-rpath,'+run([CONFIG,'--libdir']).stdout.strip(),'-o',d/'driver'])
 for name,(ir,want) in cases.items():
  (d/'input.ll').write_text(ir);output=run([d/'driver',d/'input.ll']).stdout;got=int(output.splitlines()[0]);assert got==want,(name,got);assert ('llvm.loop.unroll.disable' in output)==bool(want),(name,output);print('PASS',name)
