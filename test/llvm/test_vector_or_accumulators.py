#!/usr/bin/env python3
"""Check the wide vector OR accumulators against their shape and by execution.

Four `acc_k = phi(0, acc_k | x_k)` recurrences over vectors of at least 512 bits, combined by
an OR tree feeding one `vector.reduce.or`, become one chained recurrence: each update ORs
into the previous one, the first phi carries the chain, and the other phis are deleted.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def accumulators(lanes=16, count=4, seed='zeroinitializer', disjoint='', triple='arm64-apple-darwin'):
    vector = f'<{lanes} x i32>'
    phis = ''.join(f'  %a{k} = phi {vector} [{seed}, %entry], [%u{k}, %loop]\n' for k in range(count))
    body = ''.join(f'  %g{k} = getelementptr {vector}, ptr %row, i64 {k}\n  %x{k} = load {vector}, ptr %g{k}\n'
                   f'  %u{k} = or {disjoint}{vector} %a{k}, %x{k}\n' for k in range(count))
    names, tree, level = [f'%u{k}' for k in range(count)], '', 0
    while len(names) > 1:
        paired = []
        for j in range(0, len(names), 2):
            if j + 1 < len(names):
                tree += f'  %t{level}_{j} = or {vector} {names[j]}, {names[j + 1]}\n'
                paired.append(f'%t{level}_{j}')
            else:
                paired.append(names[j])
        names, level = paired, level + 1
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "{triple}"
declare i32 @llvm.vector.reduce.or.v{lanes}i32({vector})
define i32 @f(ptr %base, i64 %n) {{
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i2, %loop]
{phis}  %row = getelementptr {vector}, ptr %base, i64 %i
{body}  %i2 = add i64 %i, 1
  %more = icmp ult i64 %i2, %n
  br i1 %more, label %loop, label %exit
exit:
{tree}  %r = call i32 @llvm.vector.reduce.or.v{lanes}i32({vector} {names[0]})
  ret i32 %r
}}
'''


BASE = accumulators()
CASES = {
    'four_accumulators': (BASE, 1),
    'wider_vectors': (accumulators(lanes=32), 1),
    'narrow_vectors': (accumulators(lanes=8), 0),
    'three_accumulators': (accumulators(count=3), 0),
    'nonzero_seed': (accumulators(seed='splat (i32 1)'), 0),
    'disjoint_updates': (accumulators(disjoint='disjoint '), 0),
    'non_arm': (accumulators(triple='x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('vector-or-accumulators', ir)
    assert got == want, (name, got)
    assert ('%a1 = phi' not in module) == bool(want), (name, module)
    print('PASS', name)

with tempfile.TemporaryDirectory(prefix='vector-or-accumulators-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'original.ll').write_text(BASE)
    (d / 'chained.ll').write_text(run_pass('vector-or-accumulators', BASE)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern uint32_t f(const uint32_t *, uint64_t), g(const uint32_t *, uint64_t);
int main(void) {
  static uint32_t rows[64 * 64];
  uint32_t state = 11;
  for (int trial = 0; trial < 32; ++trial) {
    for (int i = 0; i < 64 * 64; ++i) {
      state = state * 1103515245u + 12345u;
      rows[i] = (state >> 7) & (1u << (state % 32));
    }
    for (uint64_t n = 1; n <= 12; ++n)
      if (f(rows, n) != g(rows, n)) return 1;
  }
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'original.ll', d / 'chained.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
