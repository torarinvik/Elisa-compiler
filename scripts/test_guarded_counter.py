#!/usr/bin/env python3
"""Verify bounded conditional counter induction and conservative rejections."""
import os,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CONFIG=os.environ.get('LLVM_CONFIG','/opt/homebrew/opt/llvm@23/bin/llvm-config')
def run(c):return subprocess.run(list(map(str,c)),capture_output=True,text=True,check=True,timeout=28)
def flags(*a):return shlex.split(run([CONFIG,*a]).stdout)
DRIVER='''#include <llvm/IRReader/IRReader.h>\n#include <llvm/Support/SourceMgr.h>\n#include <llvm/IR/Verifier.h>\n#include "llvm_guarded_increment.cpp"\n#include "llvm_guarded_counter.cpp"\nint main(int n,char**v){llvm::LLVMContext c;llvm::SMDiagnostic e;auto m=llvm::parseIRFile(v[1],e,c);if(!m){e.print(v[0],llvm::errs());return 2;}auto count=foldGuardedCounters(*m);if(llvm::verifyModule(*m,&llvm::errs()))return 3;llvm::outs()<<count<<"\\n";m->print(llvm::outs(),nullptr);}\n'''
IR='''target triple = "TRIPLE"
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
define i64 @f(i64 %n) {
entry:
 %bad = icmp ugt i64 %n, 9999
 br i1 %bad, label %invalid, label %pre
pre: br label %loop
loop:
 %cursor = phi i64 [2, %pre], [%next, %latch]
 %count = phi i64 [2, %pre], [%chosen, %latch]
 %low = and i64 %cursor, 1
 %even = icmp eq i64 %low, 0
 br i1 %even, label %increment, label %latch
increment:
 %pair = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %count, i64 1)
 %sum = extractvalue { i64, i1 } %pair, 0
 %overflow = extractvalue { i64, i1 } %pair, 1
 br i1 %overflow, label %trap, label %latch
trap:
 call void @llvm.trap()
 unreachable
latch:
 %chosen = phi i64 [%count, %loop], [%sum, %increment]
 %next = add i64 %cursor, 1
 %done = icmp sgt i64 %next, %n
 br i1 %done, label %exit, label %loop
exit: ret i64 %chosen
invalid: ret i64 -1
}
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
cases={'bounded':(IR,1),'unbounded':(IR.replace('icmp ugt i64 %n, 9999','icmp eq i64 %n, -1'),0),'different_seed':(IR.replace('%cursor = phi i64 [2,','%cursor = phi i64 [3,'),0),'cursor_step_two':(IR.replace('add i64 %cursor, 1','add i64 %cursor, 2'),0),'count_step_two':(IR.replace('i64 %count, i64 1)','i64 %count, i64 2)'),0),'wrong_latch':(IR.replace('icmp sgt i64 %next, %n','icmp sge i64 %next, %n'),0),'unknown_update':(IR.replace('[%sum, %increment]','[42, %increment]'),0),'non_arm':(IR.replace(os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'),'x86_64-unknown-linux-gnu'),0),'sanitized':(IR.replace('@f(i64 %n) {','@f(i64 %n) sanitize_address {'),0)}
with tempfile.TemporaryDirectory(prefix='guarded-counter-') as tmp:
 d=Path(tmp);(d/'driver.cpp').write_text(DRIVER);bindir=Path(run([CONFIG,'--bindir']).stdout.strip())
 run([bindir/'clang++',*flags('--cxxflags'),'-I'+str(ROOT/'src/backend'),d/'driver.cpp',*flags('--ldflags','--libs','--system-libs'),'-Wl,-rpath,'+run([CONFIG,'--libdir']).stdout.strip(),'-o',d/'driver'])
 for name,(ir,want) in cases.items():
  (d/'input.ll').write_text(ir);out=run([d/'driver',d/'input.ll']).stdout;got=int(out.splitlines()[0]);assert got==want,(name,got);assert ('add nsw i64 %count, 1' in out)==bool(want),(name,out);print('PASS',name)
 (d/'input.ll').write_text(IR);(d/'optimized.ll').write_text(run([d/'driver',d/'input.ll']).stdout.split('\n',1)[1]);(d/'main.c').write_text(r'''#include <stdint.h>
#include <limits.h>
extern int64_t f(int64_t);
int main(void){for(int64_t n=0;n<=9999;n++){int64_t max=n<2?2:n;int64_t expect=2+max/2;if(f(n)!=expect)return 1;}if(f(-1)!=-1||f(INT64_MAX)!=-1)return 2;return 0;}
''')
 for name in ('input.ll','optimized.ll'):
  run([bindir/'clang','-O2',d/name,d/'main.c','-o',d/'check']);run([d/'check'])
 print('PASS linked dense regression')
