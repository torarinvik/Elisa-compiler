#!/usr/bin/env python3
"""Check signed increment proofs against guard, boundary and control-flow cases."""
import os,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CONFIG=os.environ.get('LLVM_CONFIG','/opt/homebrew/opt/llvm@23/bin/llvm-config')
def run(c):return subprocess.run(list(map(str,c)),capture_output=True,text=True,check=True,timeout=28)
def flags(*a):return shlex.split(run([CONFIG,*a]).stdout)
DRIVER='''#include <llvm/IRReader/IRReader.h>\n#include <llvm/Support/SourceMgr.h>\n#include <llvm/IR/Verifier.h>\n#include "llvm_guarded_increment.cpp"\nint main(int n,char**v){llvm::LLVMContext c;llvm::SMDiagnostic e;auto m=llvm::parseIRFile(v[1],e,c);if(!m){e.print(v[0],llvm::errs());return 2;}auto count=foldGuardedIncrements(*m);if(llvm::verifyModule(*m,&llvm::errs()))return 3;llvm::outs()<<count<<"\\n";m->print(llvm::outs(),nullptr);}\n'''
IR='''target triple = "TRIPLE"
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
define i64 @f(i64 %x, i64 %n) {
entry:
 %shift = add i64 %n, -63
 %bad = icmp ult i64 %shift, -62
 br i1 %bad, label %out, label %check
check:
 %above = icmp sgt i64 %x, %n
 br i1 %above, label %out, label %add
add:
 %pair = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %x, i64 1)
 %value = extractvalue { i64, i1 } %pair, 0
 %overflow = extractvalue { i64, i1 } %pair, 1
 br i1 %overflow, label %trap, label %success
trap:
 call void @llvm.trap()
 unreachable
success:
 ret i64 %value
out:
 ret i64 -1
}
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
cases={'bounded':(IR,1),'unbounded':(IR.replace('icmp ult i64 %shift, -62','icmp ult i64 %shift, 1'),0),'wrong_edge':(IR.replace('br i1 %above, label %out, label %add','br i1 %above, label %add, label %out'),0),'wrong_guard':(IR.replace('icmp sgt i64 %x, %n','icmp ugt i64 %x, %n'),0),'increment_two':(IR.replace('i64 %x, i64 1)','i64 %x, i64 2)'),0),'max_bound':(IR.replace('icmp sgt i64 %x, %n','icmp sgt i64 %x, 9223372036854775807'),0),'non_arm':(IR.replace(os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'),'x86_64-unknown-linux-gnu'),0),'sanitized':(IR.replace('@f(i64 %x, i64 %n) {','@f(i64 %x, i64 %n) sanitize_address {'),0)}
with tempfile.TemporaryDirectory(prefix='guarded-increment-') as tmp:
 d=Path(tmp);(d/'driver.cpp').write_text(DRIVER);bindir=Path(run([CONFIG,'--bindir']).stdout.strip())
 run([bindir/'clang++',*flags('--cxxflags'),'-I'+str(ROOT/'src/backend'),d/'driver.cpp',*flags('--ldflags','--libs','--system-libs'),'-Wl,-rpath,'+run([CONFIG,'--libdir']).stdout.strip(),'-o',d/'driver'])
 for name,(ir,want) in cases.items():
  (d/'input.ll').write_text(ir);out=run([d/'driver',d/'input.ll']).stdout;got=int(out.splitlines()[0]);assert got==want,(name,got);assert ('add nsw i64 %x, 1' in out)==bool(want),(name,out);print('PASS',name)

 # Exercise the transformed function at the signed limits and throughout a
 # dense range, with and without the enabling guard.
 (d/'input.ll').write_text(IR)
 out=run([d/'driver',d/'input.ll']).stdout.split('\n',1)[1]
 (d/'optimized.ll').write_text(out)
 (d/'main.c').write_text(r"""#include <stdint.h>
#include <limits.h>
extern int64_t f(int64_t, int64_t);
int main(void) {
  for (int64_t n=-128; n<128; ++n) for (int64_t x=-128; x<128; ++x) {
    int64_t expect=(n>=1 && n<=62 && x<=n) ? x+1 : -1;
    if (f(x,n)!=expect) return 1;
  }
  if (f(INT64_MIN,62)!=INT64_MIN+1 || f(INT64_MAX,62)!=-1 || f(0,INT64_MAX)!=-1) return 2;
  return 0;
}
""")
 for ir in ('input.ll','optimized.ll'):
  run([bindir/'clang','-O2',d/ir,d/'main.c','-o',d/'check']);run([d/'check'])
 print('PASS linked boundary regression')
