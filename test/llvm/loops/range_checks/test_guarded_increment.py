#!/usr/bin/env python3
"""Check signed increment proofs against guard, boundary and control-flow cases.

`llvm.sadd.with.overflow(x, 1)` whose flag only feeds a branch becomes `add nsw x, 1`
when a dominating `x <= n` guard and a guard keeping `n` below the signed maximum hold.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=60)


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
for name, (ir, want) in cases.items():
    got, module = run_pass('guarded-increments', ir)
    assert got == want, (name, got)
    assert ('add nsw i64 %x, 1' in module) == bool(want), (name, module)
    print('PASS', name)

# Exercise the transformed function at the signed limits and throughout a dense range,
# with and without the enabling guard.
with tempfile.TemporaryDirectory(prefix='guarded-increment-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'input.ll').write_text(IR)
    (d / 'optimized.ll').write_text(run_pass('guarded-increments', IR)[1])
    (d / 'main.c').write_text(r"""#include <stdint.h>
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
    for ir in ('input.ll', 'optimized.ll'):
        run([bindir / 'clang', '-O2', d / ir, d / 'main.c', '-o', d / 'check'])
        run([d / 'check'])
    print('PASS linked boundary regression')
