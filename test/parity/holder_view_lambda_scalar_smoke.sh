#!/usr/bin/env bash
# Lambda parameters with proven scalar types cannot carry a local view or reference.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 - "$RPT" <<'PY'
import subprocess
import sys

reporter = sys.argv[1]
cases = (
    ("generic scalar callback", '''struct Holder:
    value: sview
def apply[T](seed: T, g: fn(T, T) -> T) -> T:
    return g(seed, seed)
def f() -> i64:
    return apply(0, fn(a, b) => a + b)
''', False),
    ("generic reference callback", '''struct Holder:
    value: sview
def apply[T](seed: T, g: fn(T, T) -> T) -> T:
    return g(seed, seed)
def f(seed: sview) -> void:
    apply(seed, fn(a, b) => a + b)
''', True),
    ("conflicting generic arguments", '''struct Holder:
    value: sview
def apply[T](first: T, second: T, g: fn(T, T) -> T) -> T:
    return g(first, second)
def f(seed: sview) -> void:
    apply(0, seed, fn(a, b) => a + b)
''', True),
    ("generic bound is not a parameter", '''struct Holder:
    value: sview
struct R:
    value: sview
def apply[T: R](seed: R, g: fn(R, R) -> R) -> R:
    return g(seed, seed)
def f() -> void:
    apply(0, fn(a, b) => a + b)
''', True),
    ("contextual scalars", '''struct Holder:
    value: sview
def apply(g: fn(i64, i64) -> i64) -> i64:
    return g(1, 2)
def f() -> i64:
    return apply(fn(a, b) => a + b)
''', False),
    ("overloaded callback", '''struct Holder:
    value: sview
def apply(g: fn(i64, i64) -> i64) -> void:
    pass
def apply(g: fn(sview, sview) -> sview) -> void:
    pass
def f() -> void:
    apply(fn(a, b) => a + b)
''', True),
    ("named callback argument", '''struct Holder:
    value: sview
def apply(g: fn(i64, i64) -> i64) -> void:
    pass
def f() -> void:
    apply(g: fn(a, b) => a + b)
''', True),
    ("imported callable ambiguity", '''using Other
struct Holder:
    value: sview
def apply(g: fn(i64, i64) -> i64) -> void:
    pass
def f() -> void:
    apply(fn(a, b) => a + b)
''', True),
    ("shadowed callable", '''struct Holder:
    value: sview
def apply(g: fn(i64, i64) -> i64) -> void:
    pass
def f(apply: fn(fn(sview, sview) -> sview) -> void) -> void:
    apply(fn(a, b) => a + b)
''', True),
    ("explicit scalars", '''struct Holder:
    value: sview

def f() -> i64:
    add = fn(a: i64, b: i64) => a + b
    return add(1, 2)
''', False),
    ("untyped parameters", '''struct Holder:
    value: sview

def f() -> void:
    add = fn(a, b) => a + b
''', True),
    ("annotated references", '''struct Holder:
    value: sview
def f() -> void:
    add = fn(a: i64&, b: i64&) => a + b
''', True),
    ("shadowed scalar name", '''struct Holder:
    value: sview
struct i64:
    value: sview

def f() -> void:
    add = fn(a: i64, b: i64) => a + b
''', True),
)
for name, source, want_escape in cases:
    result = subprocess.run([reporter], input=source, text=True, capture_output=True,
                            timeout=20, check=True)
    if not result.stdout.startswith("P 0\n"):
        raise SystemExit(f"{name}: parse failed:\n{result.stdout}")
    found = "short-lived region escapes via store" in result.stdout
    if found != want_escape:
        raise SystemExit(f"{name}: wrong escape diagnostic:\n{result.stdout}")
# Two lambdas on one source line must use their own parameter metadata.
same_line = """struct Holder:
    value: sview

def combine(left: fn(i64, i64) -> i64, right: fn(sview, sview) -> sview) -> void:
    pass

def f() -> void:
    combine(fn(a: i64, b: i64) => a + b, fn(a, b) => a + b)
"""
result = subprocess.run([reporter], input=same_line, text=True, capture_output=True,
                        timeout=20, check=True)
if not result.stdout.startswith("P 0\n") or result.stdout.count("short-lived region escapes via store") != 2:
    raise SystemExit("same-line lambda metadata was mixed:\n" + result.stdout)
print(f"holder view lambda scalar precision OK: {len(cases)} cases and same-line isolation")
PY
