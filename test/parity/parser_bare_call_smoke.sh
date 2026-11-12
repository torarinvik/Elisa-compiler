#!/usr/bin/env bash
# Statement-position calls without parentheses accept one complete expression.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 - "$RPT" <<'PY'
import subprocess
import sys

reporter = sys.argv[1]
program = '''def consume(value: i64) -> void:
    pass

def test(x: i64) -> void:
    consume x * 3 + 1
    consume (x + 2)
    consume(x)
'''
result = subprocess.run([reporter], input=program, text=True, capture_output=True,
                        timeout=20, check=True)
lines = result.stdout.splitlines()
if not lines or lines[0] != "P 0" or "D 0" not in lines:
    raise SystemExit("bare-call parsing or resolution failed:\n" + result.stdout)
print("bare-call parser and resolver smoke OK")
PY
