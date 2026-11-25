#!/usr/bin/env python3
"""Check the bounded quotient-sum versioning against its shape and by execution.

`sum = 0; while n: n /= base; sum += n` for an input at most a bound under 2^31 is the sum of
`n / base^k` over the base's powers up to the bound. With seven to twelve such powers, the
loop becomes pairwise-added 32-bit divisions, in a tier for inputs past base^6 and one with
the first five powers below it.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def quotient_loop(base=5, bound=100000000, triple='arm64-apple-darwin', seed=0, exact=''):
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "{triple}"
define i64 @f(i64 %n) {{
entry:
  %big = icmp ugt i64 %n, {bound}
  br i1 %big, label %fallback, label %pre
fallback:
  ret i64 -1
pre:
  %z = icmp eq i64 %n, 0
  br i1 %z, label %exit, label %body
body:
  %w = phi i64 [%n, %pre], [%q, %body]
  %s = phi i64 [{seed}, %pre], [%a, %body]
  %q = udiv {exact}i64 %w, {base}
  %a = add i64 %s, %q
  %d = icmp ult i64 %w, {base}
  br i1 %d, label %exit, label %body
exit:
  %r = phi i64 [0, %pre], [%a, %body]
  ret i64 %r
}}
'''


CASES = {
    'base_five': (quotient_loop(), 1),
    'base_three': (quotient_loop(base=3, bound=1000000), 1),
    'base_sixteen': (quotient_loop(base=16, bound=2147483647), 1),
    'base_two': (quotient_loop(base=2), 0),
    'too_few_powers': (quotient_loop(base=10, bound=999999), 0),
    'too_many_powers': (quotient_loop(base=3, bound=2000000000), 0),
    'bound_past_31_bits': (quotient_loop(bound=2147483648), 0),
    'nonzero_seed': (quotient_loop(seed=1), 0),
    'exact_division': (quotient_loop(exact='exact '), 0),
    'non_arm': (quotient_loop(triple='x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('bounded-quotient-sums', ir)
    assert got == want, (name, got)
    assert ('quotient.sum.parallel' in module) == bool(want), (name, module)
    assert ('body:' in module) != bool(want), (name, module)
    print('PASS', name)

# The versioned sums agree with the loops on and around every power and the bound.
with tempfile.TemporaryDirectory(prefix='bounded-quotient-sums-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    variants = (('five', quotient_loop(), 5, 100000000), ('three', quotient_loop(base=3, bound=1000000), 3, 1000000),
                ('sixteen', quotient_loop(base=16, bound=2147483647), 16, 2147483647))
    for label, ir, _, _ in variants:
        (d / f'{label}.ll').write_text(ir.replace('@f(', f'@f_{label}('))
        (d / f'{label}_versioned.ll').write_text(run_pass('bounded-quotient-sums', ir)[1].replace('@f(', f'@g_{label}('))
    checks = '\n'.join(f'  if (!same(f_{label}, g_{label}, {base}ull, {bound}ull)) return 1;' for label, _, base, bound in variants)
    declarations = '\n'.join(f'extern uint64_t f_{label}(uint64_t), g_{label}(uint64_t);' for label, _, _, _ in variants)
    (d / 'main.c').write_text(r"""#include <stdint.h>
typedef uint64_t (*sum_fn)(uint64_t);
""" + declarations + r"""
static int agree(sum_fn original, sum_fn versioned, uint64_t n) { return original(n) == versioned(n); }
static int same(sum_fn original, sum_fn versioned, uint64_t base, uint64_t bound) {
  for (uint64_t n = 0; n < 5000; ++n)
    if (!agree(original, versioned, n)) return 0;
  for (uint64_t power = base; power <= bound; power *= base)
    for (uint64_t near = power - 2; near <= power + 2; ++near)
      if (!agree(original, versioned, near)) return 0;
  for (uint64_t n = bound - 3; n <= bound + 3; ++n)
    if (!agree(original, versioned, n)) return 0;
  return 1;
}
int main(void) {
""" + checks + r"""
  return 0;
}
""")
    sources = [d / f'{label}{suffix}.ll' for label, _, _, _ in variants for suffix in ('', '_versioned')]
    run([bindir / 'clang', '-O1', '-Wno-override-module', *sources, d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
