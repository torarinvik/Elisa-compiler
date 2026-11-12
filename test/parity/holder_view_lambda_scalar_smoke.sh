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
print(f"holder view lambda scalar precision OK: {len(cases)} cases")
PY
