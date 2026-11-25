#!/usr/bin/env python3
"""Check the small-recursion passes against their shapes.

`recursive-inline` expands small private recursion on AArch64 macOS and Linux without
debug info: checked-accumulator recursion becomes loops, literal arguments get
specialized copies, small binary and guarded linear recursion inline snapshots of
themselves, and the O3 cleanup is followed by zero versioning, accumulator proofs and
guard bias. Each step also runs alone. Each case's count, and the functions, calls,
overflow checks and conditional branches it leaves, are what the C++ passes did with
the same shapes (recursion_cases.py).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from recursion_cases import CASES, EXPECTED, PASSES, run_mode


def shape(count, module):
    definitions = len(re.findall(r'^define ', module, re.M))
    calls = len(re.findall(r'\bcall (?!void @llvm\.trap)', module))
    checks = len(re.findall(r'call \{[^}]*\} @llvm\.[su](?:add|sub|mul)\.with\.overflow', module))
    branches = len(re.findall(r'\bbr i1 ', module))
    return count, definitions, calls, checks, branches


def main():
    for name, (mode, ir) in CASES.items():
        count, module = run_mode(mode, ir)
        got = shape(count, module)
        assert got == EXPECTED[name], (name, PASSES[mode], got, EXPECTED[name])
        print('PASS', name, flush=True)
    print('recursion: counts and shapes passed')


if __name__ == '__main__':
    main()
