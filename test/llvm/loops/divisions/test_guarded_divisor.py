#!/usr/bin/env python3
"""Check the loop-divisor versioning, its rejection gates, and runtime behavior.

The versioned function must compute what the original did for every divisor, the
specialized value 2 included.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

ROOT = Path(__file__).resolve().parents[4]
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm/bin/llvm-config')

def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=28)

HARNESS = r'''#include <stdint.h>
#include <stdio.h>
extern int64_t work(int64_t *, int64_t *, _Bool);
int main(void) {
  int64_t count = 0;
  printf("%lld ", (long long)work(0, &count, 0));
  for (int64_t i = 0; i < 18; ++i) {
    int64_t n = i / 2;
    printf("%lld:%lld ", (long long)work(&n, &count, i & 1), (long long)count);
  }
  printf("%lld\n", (long long)count);
}
'''

def replace_once(s, old, new):
    assert s.count(old) == 1, old
    return s.replace(old, new, 1)

base = (ROOT / 'test/fixtures/guarded_divisor_version.ll').read_text()
cases = {
    'covered': (base, 1),
    'volatile_load': (replace_once(base, '%raw = load i64', '%raw = load volatile i64'), 0),
    'single_remainder': (replace_once(base, '%r2 = urem i64 %i1, %div', '%r2 = add i64 %i1, %div'), 0),
    'external_call': (replace_once(base, 'prefix:\n', 'prefix:\n  call void @effect()\n') + '\ndeclare void @effect()\n', 0),
    'size_optimized': (replace_once(base, 'define i64 @work(ptr %input, ptr %count, i1 %skip) {', 'define i64 @work(ptr %input, ptr %count, i1 %skip) optsize {'), 0),
    'address_sanitizer': (replace_once(base, 'define i64 @work(ptr %input, ptr %count, i1 %skip) {', 'define i64 @work(ptr %input, ptr %count, i1 %skip) sanitize_address {'), 0),
    'complex_loop_metadata': (replace_once(base, '!1 = !{!"llvm.loop.unroll.disable"}', '!1 = !{!"llvm.loop.unroll.followup_all", !2}') + '\n!2 = distinct !{!2}\n', 0),
    'alias_scope': (replace_once(base, '%raw = load i64, ptr %input', '%raw = load i64, ptr %input, !alias.scope !2') + '\n!2 = !{!3}\n!3 = distinct !{!3, !4}\n!4 = distinct !{!4}\n', 0),
}
with tempfile.TemporaryDirectory(prefix='guarded-divisor-') as temp:
    d = Path(temp)
    (d/'harness.c').write_text(HARNESS)
    clang = str(Path(run([CONFIG, '--bindir']).stdout.strip())/'clang')
    for name, (ir, expected) in cases.items():
        changed, module = run_pass('divisor-versioning', ir)
        assert changed == expected, (name, changed, expected)
        assert ('.divisor2' in module) == bool(expected), (name, module)
        if name == 'covered':
            source, transformed = d/(name+'.ll'), d/(name+'-out.ll')
            source.write_text(ir)
            transformed.write_text(module)
            for suffix, path in [('original', source), ('changed', transformed)]:
                run([clang, '-O2', str(path), str(d/'harness.c'), '-o', str(d/suffix)])
            assert run([str(d/'original')]).stdout == run([str(d/'changed')]).stdout
        print('PASS', name)
