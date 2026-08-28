#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$(command -v clang || true)" ]]; then
    echo "pymodule enum smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/enums.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_enums.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import enums

assert enums.mode_roundtrip(0) == 0
assert enums.mode_roundtrip(7) == 7
assert enums.plain_roundtrip(0) == 0
assert enums.plain_roundtrip(1) == 1
assert enums.mode_count([0, 7, 7]) == 3
print("pymodule enum smoke OK")
PY
