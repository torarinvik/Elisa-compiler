#!/usr/bin/env python3
"""Check nonnegative recurrence proofs and signed-remainder rejection cases."""
import os,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CONFIG=os.environ.get('LLVM_CONFIG','/opt/homebrew/opt/llvm@23/bin/llvm-config')
def run(c):return subprocess.run(list(map(str,c)),capture_output=True,text=True,check=True,timeout=28)
def flags(*a):return shlex.split(run([CONFIG,*a]).stdout)
DRIVER='''#include <llvm/IRReader/IRReader.h>\n#include <llvm/Support/SourceMgr.h>\n#include <llvm/IR/Verifier.h>\n#include "llvm_nonnegative_remainder.cpp"\nint main(int n,char**v){llvm::LLVMContext c;llvm::SMDiagnostic e;auto m=llvm::parseIRFile(v[1],e,c);if(!m){e.print(v[0],llvm::errs());return 2;}auto count=foldNonnegativeRemainders(*m);if(llvm::verifyModule(*m,&llvm::errs()))return 3;llvm::outs()<<count<<"\\n";m->print(llvm::outs(),nullptr);}\n'''
IR='''target triple = "TRIPLE"
define i64 @f(ptr %p, i64 %n) {
entry:
 %empty = icmp eq i64 %n, 0
 br i1 %empty, label %zero, label %loop
zero: ret i64 5381
loop:
 %i = phi i64 [0, %entry], [%next, %step]
 %hash = phi i64 [5381, %entry], [%rem, %step]
 %ptr = getelementptr i64, ptr %p, i64 %i
 %code = load i64, ptr %ptr
 %bad = icmp ugt i64 %code, 255
 br i1 %bad, label %invalid, label %step
step:
 %scaled = mul nsw i64 %hash, 33
 %sum = add nsw i64 %scaled, %code
 %rem = srem i64 %sum, 4294967296
 %next = add i64 %i, 1
 %done = icmp eq i64 %next, %n
 br i1 %done, label %exit, label %loop
exit: ret i64 %rem
invalid: ret i64 -1
}
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
cases={'guarded_recurrence':(IR,1),'negative_seed':(IR.replace('[5381, %entry], [%rem','[-1, %entry], [%rem'),0),'signed_guard':(IR.replace('icmp ugt i64 %code, 255','icmp sgt i64 %code, 255'),0),'inverted_guard':(IR.replace('br i1 %bad, label %invalid, label %step','br i1 %bad, label %step, label %invalid'),0),'undefined_seed':(IR.replace('[5381, %entry], [%rem','[undef, %entry], [%rem'),0),'subtract':(IR.replace('add nsw i64 %scaled, %code','sub nsw i64 %scaled, %code'),0),'missing_nsw_mul':(IR.replace('mul nsw i64','mul i64'),0),'missing_nsw_add':(IR.replace('add nsw i64','add i64'),0),'negative_term':(IR.replace('%scaled, %code','%scaled, -1'),0),'non_power_two':(IR.replace('srem i64 %sum, 4294967296','srem i64 %sum, 4294967295'),0),'negative_divisor':(IR.replace('srem i64 %sum, 4294967296','srem i64 %sum, -4294967296'),0),'non_arm':(IR.replace(os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'),'x86_64-unknown-linux-gnu'),0),'sanitized':(IR.replace('@f(ptr %p, i64 %n) {','@f(ptr %p, i64 %n) sanitize_address {'),0)}
with tempfile.TemporaryDirectory(prefix='nonnegative-rem-') as tmp:
 d=Path(tmp);(d/'driver.cpp').write_text(DRIVER);bindir=Path(run([CONFIG,'--bindir']).stdout.strip())
 run([bindir/'clang++',*flags('--cxxflags'),'-I'+str(ROOT/'src/backend'),d/'driver.cpp',*flags('--ldflags','--libs','--system-libs'),'-Wl,-rpath,'+run([CONFIG,'--libdir']).stdout.strip(),'-o',d/'driver'])
 for name,(ir,want) in cases.items():
  (d/'input.ll').write_text(ir);out=run([d/'driver',d/'input.ll']).stdout;got=int(out.splitlines()[0]);assert got==want,(name,got);assert ('urem i64 %sum, 4294967296' in out)==bool(want),(name,out);print('PASS',name)
 (d/'input.ll').write_text(IR);(d/'optimized.ll').write_text(run([d/'driver',d/'input.ll']).stdout.split('\n',1)[1]);(d/'main.c').write_text(r'''#include <stdint.h>
extern int64_t f(const int64_t*, uint64_t);
int main(void){int64_t a[64];for(int t=0;t<500;t++){uint32_t h=5381;for(int i=0;i<64;i++){a[i]=(i*71+t*13)&255;h=h*33+(uint32_t)a[i];if(f(a,i+1)!=(int64_t)h)return 1;}a[t%64]=-1;if(f(a,64)!=-1)return 2;a[t%64]=256;if(f(a,64)!=-1)return 3;}if(f(a,0)!=5381)return 4;return 0;}
''')
 for ir in ('input.ll','optimized.ll'):
  run([bindir/'clang','-O2',d/ir,d/'main.c','-o',d/'check']);run([d/'check'])
 print('PASS linked recurrence regression')
