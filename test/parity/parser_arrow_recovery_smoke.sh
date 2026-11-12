#!/usr/bin/env bash
# A damaged header must not consume the next function's return arrow.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
out="$("$RPT" < "$REPO_ROOT/test/repro/parser_arrow_recovery.elisa")"
if ! grep -q '^P 1$' <<< "$out" || ! grep -q '^  0 L1 -$' <<< "$out"; then
    printf 'parser arrow recovery smoke FAILED:\n%s\n' "$out" >&2
    exit 1
fi
echo 'parser arrow recovery smoke OK'
python3 - "$RPT" <<'PY'
import subprocess
import sys

reporter = sys.argv[1]
cases = (
    ("def broken(x: i64)\n4:\n    return x\n", False),
    ("def broken(x: i64)\n42:\n    return x\n", False),
    ("def good(\n    x: i64\n) -> i64:\n    return x\n", True),
)
for source, accepted in cases:
    result = subprocess.run([reporter], input=source, text=True, capture_output=True,
                            timeout=20, check=True)
    first = result.stdout.splitlines()[0]
    count = int(first.split()[1]) if first.startswith("P ") else -1
    if count < 0 or (count == 0) != accepted:
        raise SystemExit(f"header recovery mismatch for {source!r}: {result.stdout}")
print("multiline header recovery OK")
PY

python3 - "$RPT" <<'PYTEST'
import subprocess
import sys

reporter = sys.argv[1]
header = "def target(first: mutable darray[i64]&) -> void:\n    pass\n"
cases = (
    ("valid", "export fn exposed(first: mutable darray[i64]&) -> void = target\n", True),
    ("valid two parameters", "export fn exposed(first: i64, second: i64) -> void = target\n", True),
    ("extra parameter name", "export fn exposed(first: mutable dart: mutable darray[i64]&) -> void = target\n", False),
    ("missing comma", "export fn exposed(first: i64 second: i64) -> void = target\n", False),
)
for name, source, accepted in cases:
    result = subprocess.run([reporter], input=header + source, text=True, capture_output=True, timeout=20, check=True)
    lines = result.stdout.splitlines()
    count = int(lines[0].split()[1]) if lines and lines[0].startswith("P ") else -1
    if count < 0 or (count == 0) != accepted or (not accepted and "expected comma between extern parameters" not in result.stdout):
        raise SystemExit(f"export parameter recovery failed ({name}): {result.stdout}")
print("export parameter recovery OK")
PYTEST
