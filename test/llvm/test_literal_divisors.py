#!/usr/bin/env python3
"""Check the literal divisor specialization against its shape and by execution.

A local helper dividing by one of its i32 arguments at least twice, called with exactly two
literal divisors, is cloned once per literal so each clone divides by a constant. A clone
with one call inside a loop is inlined into its caller. `elisac llvm-pass` runs the pass's
cleanups without a target machine.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')


def run(command):
    return subprocess.run(list(map(str, command)), capture_output=True, text=True, check=True, timeout=120)


def program(literals=(10, 7), loop=True, linkage='internal', second='urem', extra='', triple='arm64-apple-darwin'):
    filler = ''.join(f'  %t{k} = add i64 %acc{k}, {k + 3}\n  %acc{k + 1} = mul i64 %t{k}, 3\n' for k in range(6))
    calls = ''.join(f'  %c{k} = call i64 @helper(i32 %narrow, i32 {literal})\n' for k, literal in enumerate(literals))
    sums = ''.join(f'  %s{k + 1} = add i64 %s{k}, %c{k}\n' for k in range(len(literals)))
    last = f'%s{len(literals)}'
    if loop:
        caller = f'''define i64 @caller(i64 %n, ptr %p) {{
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%i2, %loop]
  %s0 = phi i64 [0, %entry], [{last}, %loop]
  %slot = getelementptr i64, ptr %p, i64 %i
  %value = load i64, ptr %slot
  %narrow = trunc i64 %value to i32
{calls}{sums}  %i2 = add i64 %i, 1
  %more = icmp ult i64 %i2, %n
  br i1 %more, label %loop, label %exit
exit:
  ret i64 {last}
}}
'''
    else:
        caller = f'''define i64 @caller(i64 %value) {{
entry:
  %s0 = add i64 %value, 0
  %narrow = trunc i64 %value to i32
{calls}{sums}  ret i64 {last}
}}
'''
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "{triple}"
declare void @opaque()
define {linkage} i64 @helper(i32 %x, i32 %d) {{
entry:
  %q = udiv i32 %x, %d
  %r = {second} i32 %x, %d
  %qw = zext i32 %q to i64
  %rw = zext i32 %r to i64
  %acc0 = add i64 %qw, %rw
{extra}{filler}  ret i64 %acc6
}}
''' + caller


LOOP = program()
STRAIGHT = program(loop=False)
CASES = {
    'loop_inlined': (LOOP, 1, False),
    'straight_line_cloned': (STRAIGHT, 1, True),
    'three_literals': (program(literals=(10, 7, 9)), 0, False),
    'one_literal': (program(literals=(10, 10)), 0, False),
    'literal_one': (program(literals=(1, 7)), 0, False),
    'one_division': (program(second='add'), 0, False),
    'external_helper': (program(linkage=''), 0, False),
    'opaque_call': (program(extra='  call void @opaque()\n'), 0, False),
    'non_arm': (program(triple='x86_64-unknown-linux-gnu'), 0, False),
}

for name, (ir, want, clones_remain) in CASES.items():
    got, module = run_pass('literal-divisors', ir)
    assert got == want, (name, got)
    assert (' @helper(' not in module) == bool(want), (name, module)
    assert ('@helper.literal_divisor' in module) == clones_remain, (name, module)
    if want:
        assert 'udiv i32 %x, %d' not in module and 'udiv i32 %narrow, %d' not in module, (name, module)
    print('PASS', name)

# The specialized programs compute the same sums.
with tempfile.TemporaryDirectory(prefix='literal-divisors-') as tmp:
    d = Path(tmp)
    bindir = Path(run([CONFIG, '--bindir']).stdout.strip())
    variants = (('loop', LOOP), ('straight', STRAIGHT))
    for label, ir in variants:
        original = ir.replace('@caller(', f'@caller_{label}(').replace('@helper', f'@helper_{label}')
        specialized = run_pass('literal-divisors', ir)[1].replace('@caller(', f'@special_{label}(').replace('@helper', f'@special_helper_{label}')
        (d / f'{label}.ll').write_text(original)
        (d / f'{label}_specialized.ll').write_text(specialized)
    (d / 'main.c').write_text(r"""#include <stdint.h>
extern uint64_t caller_loop(uint64_t, const uint64_t *), special_loop(uint64_t, const uint64_t *);
extern uint64_t caller_straight(uint64_t), special_straight(uint64_t);
int main(void) {
  uint64_t values[64];
  uint64_t state = 7;
  for (int i = 0; i < 64; ++i) values[i] = state = state * 6364136223846793005ull + 1442695040888963407ull;
  for (uint64_t n = 1; n <= 64; ++n)
    if (caller_loop(n, values) != special_loop(n, values)) return 1;
  for (int i = 0; i < 64; ++i)
    if (caller_straight(values[i]) != special_straight(values[i])) return 2;
  return 0;
}
""")
    sources = [d / f'{label}{suffix}.ll' for label, _ in variants for suffix in ('', '_specialized')]
    run([bindir / 'clang', '-O1', '-Wno-override-module', *sources, d / 'main.c', '-o', d / 'check'])
    run([d / 'check'])
    print('PASS execution equivalence')
