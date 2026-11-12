#!/usr/bin/env bash
# A value block's local shadow must not change later call resolution.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 - "$RPT" <<'PY'
import subprocess
import sys

reporter = sys.argv[1]
cases = (
    ('''def twice(x: i64) -> i64:
    return x * 2

def f() -> i64:
    before: i64 =
        twice: i64 = 3
        twice
    return twice(before)
''', False),
    ('''def twice(x: i64) -> i64:
    return x * 2

def f() -> i64:
    before: i64 =
        twice: i64 = 3
        twice(2)
    return before
''', True),
)
for source, bad in cases:
    result = subprocess.run([reporter], input=source, text=True, capture_output=True,
                            timeout=20, check=True)
    if not result.stdout.startswith("P 0\n"):
        raise SystemExit("unexpected parse error:\n" + result.stdout)
    found = "cannot call non-function value of type i64" in result.stdout
    if found != bad:
        raise SystemExit("wrong call-scope diagnostic:\n" + result.stdout)
print("call non-function value-block scope OK")
PY
