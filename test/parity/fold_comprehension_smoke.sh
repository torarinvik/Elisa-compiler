#!/usr/bin/env bash
# Fold forms must preserve Stage0 parsing and reject the removed SIMD spelling.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 - "$RPT" <<'PY'
import subprocess
import sys

reporter = sys.argv[1]
cases = (
    ("simple", "(acc + value for value in values with acc = 0)", True),
    ("typed binding", "(twice: i64 = value * 2, acc + twice for value in values with acc = 0)", True),
    ("filter", "(acc + value for value in values if value > 1 with acc = 0)", True),
    ("range", "(acc + value for value in 0..<10 with acc = 0)", True),
    ("parallel", "(acc + value for value in values with acc = 0 by par)", True),
    ("removed simd", "(acc + value for value in values with acc = 0 by simd)", False),
    ("parallel filter", "(acc + value for value in values if value > 0 with acc = 0 by par)", False),
    ("parallel range", "(acc + value for value in 0..<10 with acc = 0 by par)", False),
    ("parallel nonassociative", "(acc - value for value in values with acc = 0 by par)", False),
    ("parallel accumulator alone", "(acc + acc for value in values with acc = 0 by par)", False),
    ("parallel dependent call", "(acc + twice(value, acc) for value in values with acc = 0 by par)", False),
    ("parallel dependent transform", "(acc + (value + acc) for value in values with acc = 0 by par)", False),
    ("parallel dependent array", "(acc + [value, acc][0] for value in values with acc = 0 by par)", False),
    ("parallel missing accumulator", "(value + 1 for value in values with acc = 0 by par)", False),
    ("parallel binding", "(x = value, acc + x for value in values with acc = 0 by par)", False),
    ("parallel transformed", "(acc + value * 2 for value in values with acc = 0 by par)", True),
    ("specialized transform", "(acc + convert[i64, i64](value) for value in values with acc = 0)", True),
    ("shorthand transform", "(acc + choose(.Selected, value) for value in values with acc = 0)", True),
    ("set literal transform", "(acc + score({value}) for value in values with acc = 0)", True),
    ("dictionary literal transform", "(acc + score({value: 1}) for value in values with acc = 0)", True),
)
# Nested transforms accepted by Stage0 must not hit an artificially low clone limit.
for depth in (130, 990):
    nested = "value"
    for _ in range(depth):
        nested = f"({nested} + 1)"
    cases += ((f"transform depth {depth}", f"(acc + {nested} for value in values with acc = 0)", True),)
failures = []
for name, expression, accepted in cases:
    source = f"def f(values: darray[i64]) -> i64:\n    return {expression}\n"
    result = subprocess.run([reporter], input=source, text=True, capture_output=True,
                            timeout=20, check=True)
    lines = result.stdout.splitlines()
    count = int(lines[0].split()[1]) if lines and lines[0].startswith("P ") else -1
    if count < 0 or (count == 0) != accepted:
        failures.append(f"{name}: expected {'accept' if accepted else 'reject'}, got {lines[:3]}")
if failures:
    raise SystemExit("fold comprehension parser failures:\n" + "\n".join(failures))
synthetic_callbacks = '''struct Holder:
    value: sview
def slice(values: mutable darray[i64]&) -> i64:
    return 0
def map_reduce[T, U](source: i64, seed: U, transform: fn(T) -> U, op: fn(U, U) -> U) -> U:
    return seed
def f() -> i64:
    values: mutable darray[i64] = [1, 2]
    return (acc + value for value in values with acc = 0 by par)
'''
result = subprocess.run([reporter], input=synthetic_callbacks, text=True,
                        capture_output=True, timeout=20, check=True)
if result.stdout != "P 0\nD 0\n":
    raise SystemExit("parallel fold callback context failed:\n" + result.stdout)
print(f"fold comprehension parser smoke OK: {len(cases)} cases")
PY
