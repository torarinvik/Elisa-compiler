#!/usr/bin/env python3
"""Check the guarded unsigned compares against their shape and by execution.

`select (limit >u upper), true, (value <s 0) | (value >s limit)` with a nonnegative `upper`
becomes `select (limit >u upper), true, value >u limit`: where the guard is false the limit
is nonnegative, so a negative value is above it as an unsigned number.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def range_test(upper='100', negative='icmp slt i64 %v, 0', above='icmp sgt i64 %v, %limit', reject='true', triple='arm64-apple-darwin'):
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "{triple}"
define i1 @f(i64 %v, i64 %limit) {{
entry:
  %guard = icmp ugt i64 %limit, {upper}
  %neg = {negative}
  %high = {above}
  %either = or i1 %neg, %high
  %bad = select i1 %guard, i1 {reject}, i1 %either
  ret i1 %bad
}}
'''


BASE = range_test()
CASES = {
    'base': (BASE, 1),
    'zero_on_left': (range_test(negative='icmp sgt i64 0, %v'), 1),
    'limit_on_left': (range_test(above='icmp slt i64 %limit, %v'), 1),
    'negative_upper': (range_test(upper='-5'), 0),
    'inclusive_above': (range_test(above='icmp sge i64 %v, %limit'), 0),
    'reject_false': (range_test(reject='false'), 0),
    'non_arm': (range_test(triple='x86_64-unknown-linux-gnu'), 0),
}

for name, (ir, want) in CASES.items():
    got, module = run_pass('guarded-unsigned-compares', ir)
    assert got == want, (name, got)
    assert ('icmp ugt i64 %v, %limit' in module) == bool(want), (name, module)
    assert ('%either' in module) != bool(want), (name, module)
    print('PASS', name)

with tempfile.TemporaryDirectory(prefix='guarded-unsigned-compares-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    (d / 'original.ll').write_text(BASE)
    (d / 'folded.ll').write_text(run_pass('guarded-unsigned-compares', BASE)[1].replace('@f(', '@g('))
    (d / 'main.c').write_text(r"""#include <stdbool.h>
#include <stdint.h>
extern bool f(int64_t, int64_t), g(int64_t, int64_t);
int main(void) {
  const int64_t values[] = {INT64_MIN, -1000, -101, -100, -1, 0, 1, 50, 99, 100, 101, 1000, INT64_MAX};
  const int n = sizeof values / sizeof values[0];
  for (int a = 0; a < n; ++a)
    for (int b = 0; b < n; ++b)
      if (f(values[a], values[b]) != g(values[a], values[b])) return 1;
  return 0;
}
""")
    run([bindir / 'clang', '-O1', '-Wno-override-module', d / 'original.ll', d / 'folded.ll', d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
