#!/usr/bin/env bash
# Head bindings run in iteration scope and are visible to both filter and body.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 - "$RPT" "$REPO_ROOT/test/fixtures/comprehensions/fold_reduction.elisa" <<'PY'
import subprocess
import sys

reporter = sys.argv[1]
cases = (
    ("typed", "(twice: i64 = value * 2, acc + twice for value in values with acc = 0)", True),
    ("filter", "(twice: i64 = value * 2, acc + twice for value in values if twice > 2 with acc: i64 = 0)", True),
    ("multiple", "(x = value, y: i64 = x * 2, acc + y for value in values with acc = 1)", True),
    ("unsupported parallel binding", "(x = value, acc + x for value in values with acc = 0 by par)", False),
    ("unbound filter", "(acc + value for value in values if value > 1 with acc = 0)", True),
    ("unbound range", "(acc + value for value in 0..<10 with acc = 0)", True),
)
for name, expression, accepted in cases:
    source = f"def f(values: darray[i64]) -> i64:\n    return {expression}\n"
    result = subprocess.run([reporter], input=source, text=True, capture_output=True,
                            timeout=20, check=True)
    lines = result.stdout.splitlines()
    count = int(lines[0].split()[1]) if lines and lines[0].startswith("P ") else -1
    if count < 0 or (count == 0) != accepted or (accepted and "D 0" not in lines):
        raise SystemExit(f"{name}: unexpected result:\n{result.stdout}")
with open(sys.argv[2], encoding="utf-8") as fixture:
    result = subprocess.run([reporter], input=fixture.read(), text=True, capture_output=True,
                            timeout=20, check=True)
if not result.stdout.startswith("P 0\nD 0\n"):
    raise SystemExit("fold execution fixture did not parse and resolve:\n" + result.stdout)
print(f"fold parsing and resolution OK: {len(cases)} cases and execution fixture")
PY
