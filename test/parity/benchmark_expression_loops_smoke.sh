#!/usr/bin/env bash
# Keep benchmark loops in the expression form with an explicit yielded value.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - "$REPO_ROOT/test/bench" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
loops = 0
violations = []
for path in sorted(root.rglob("*.elisa")):
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("for ", "while ")):
            loops += 1
            if "->" not in stripped:
                violations.append(f"{path}:{line_number}: {line.strip()}")

if violations:
    print("benchmark loops must use expression form and yield with `->`:", file=sys.stderr)
    print("\n".join(violations), file=sys.stderr)
    raise SystemExit(1)

print(f"benchmark expression-loop smoke OK: {loops} loop headers checked")
PY
