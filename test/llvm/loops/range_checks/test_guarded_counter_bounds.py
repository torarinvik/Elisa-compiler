#!/usr/bin/env python3
"""Check the guarded counter bounds against their shape and by execution.

A loop counter seeded in [0, cap] whose only update is `+1`, reached only while the
counter differs from cap, never exceeds cap. A `counter <u bound` check on an edge where
`counter <s bound` already holds is then always true, and its uses become `true`.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def counter_loop(seed=0, cap=9, cap_test='eq', step=1, guard='slt', triple='arm64-apple-darwin', attrs=''):
    at_cap, below_cap = ('%stay', '%bump') if cap_test == 'eq' else ('%bump', '%stay')
    checked, skipped = ('%checked', '%skip') if guard == 'slt' else ('%skip', '%checked')
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "{triple}"
declare void @llvm.trap()
define i64 @f(i64 %n, ptr %p) {attrs}{{
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i2, %latch]
  %c = phi i64 [{seed}, %entry], [%next, %latch]
  %g = icmp {guard} i64 %c, 10
  br i1 %g, label {checked}, label {skipped}
checked:
  %ok = icmp ult i64 %c, 10
  br i1 %ok, label %body, label %trap
body:
  %slot = getelementptr i64, ptr %p, i64 %c
  %old = load i64, ptr %slot
  %new = add i64 %old, %i
  store i64 %new, ptr %slot
  br label %skip
skip:
  %atcap = icmp {cap_test} i64 %c, {cap}
  br i1 %atcap, label {at_cap}, label {below_cap}
bump:
  %inc = add i64 %c, {step}
  br label %latch
stay:
  br label %latch
latch:
  %next = phi i64 [%inc, %bump], [%c, %stay]
  %i2 = add i64 %i, 1
  %more = icmp ult i64 %i2, %n
  br i1 %more, label %loop, label %exit
trap:
  call void @llvm.trap()
  unreachable
exit:
  ret i64 %c
}}
'''


CASES = {
    'capped': (counter_loop(), 1),
    'not_equal_cap': (counter_loop(cap_test='ne'), 1),
    'negated_guard': (counter_loop(guard='sge'), 1),
    'cap_above_bound': (counter_loop(cap=100), 1),
    'step_two': (counter_loop(step=2), 0),
    'seed_above_cap': (counter_loop(seed=12), 0),
    'negative_cap': (counter_loop(cap=-3), 0),
    'size_optimized': (counter_loop(attrs='optsize '), 0),
    'non_arm': (counter_loop(triple='x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('guarded-counter-bounds', ir)
    assert got == want, (name, got)
    assert ('br i1 %ok,' in module) != bool(want), (name, module)
    print('PASS', name)

# The folded loops write the same slots and end on the same counter.
with tempfile.TemporaryDirectory(prefix='guarded-counter-bounds-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    variants = (('eq', counter_loop()), ('ne', counter_loop(cap_test='ne')), ('wide', counter_loop(cap=100)))
    for label, ir in variants:
        (d / f'{label}.ll').write_text(ir.replace('@f(', f'@f_{label}('))
        (d / f'{label}_folded.ll').write_text(run_pass('guarded-counter-bounds', ir)[1].replace('@f(', f'@g_{label}('))
    (d / 'main.c').write_text(r"""#include <stdint.h>
#include <string.h>
typedef uint64_t (*loop_fn)(uint64_t, uint64_t *);
extern uint64_t f_eq(uint64_t, uint64_t *), g_eq(uint64_t, uint64_t *);
extern uint64_t f_ne(uint64_t, uint64_t *), g_ne(uint64_t, uint64_t *);
extern uint64_t f_wide(uint64_t, uint64_t *), g_wide(uint64_t, uint64_t *);
static int same(loop_fn original, loop_fn folded, uint64_t n) {
  uint64_t first[10], second[10];
  memset(first, 0, sizeof first);
  memset(second, 0, sizeof second);
  return original(n, first) == folded(n, second) && memcmp(first, second, sizeof first) == 0;
}
int main(void) {
  for (uint64_t n = 1; n < 300; ++n) {
    if (!same(f_eq, g_eq, n)) return 1;
    if (!same(f_ne, g_ne, n)) return 2;
    if (!same(f_wide, g_wide, n)) return 3;
  }
  return 0;
}
""")
    sources = [d / f'{label}{suffix}.ll' for label, _ in variants for suffix in ('', '_folded')]
    run([bindir / 'clang', '-O1', '-Wno-override-module', *sources, d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
