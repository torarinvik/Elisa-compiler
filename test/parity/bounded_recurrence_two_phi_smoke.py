#!/usr/bin/env python3
"""A loop multiplying two phis must not crash the bounded-recurrence proofs. Set ELISAC to test another compiler."""
import os, subprocess, tempfile
from pathlib import Path
ELISAC = os.environ.get('ELISAC') or str(Path(__file__).resolve().parents[2] / 'bin/elisac-stage1')
SOURCE = '''def derange(n: i64) -> i64:
    if n < 2 or n > 20:
        return 0
    previous: mutable i64 = 1
    older: mutable i64 = 0
    i: mutable i64 = 3
    while i <= n:
        current: i64 = (i - 1) * (previous + older)
        older <- previous
        previous <- current
        i <- i + 1
    return previous

export fn derange_abi(n: i64) -> i64 = derange
'''
with tempfile.TemporaryDirectory(prefix='elisa-two-phi-') as tmp:
    src = Path(tmp) / 'a.elisa'
    src.write_text(SOURCE)
    subprocess.run([ELISAC, '-O3', '-emit', 'obj', '-o', str(Path(tmp) / 'a.o'), str(src)], check=True, capture_output=True, timeout=60)
print('bounded recurrence two-phi: ok')
