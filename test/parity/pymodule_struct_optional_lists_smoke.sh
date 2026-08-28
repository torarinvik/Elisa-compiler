#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$(command -v clang || true)" ]]; then
    echo "pymodule struct-optional-list smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_optional_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_optional_lists.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_optional_lists

value = {
    "signed": [None, -4, 9],
    "narrow": [None, 0, 255],
    "flags": [True, None, False],
    "ratio": [None, 1.25, -0.5],
    "labels": [None, "alpha", "beta"],
    "text": [None, "a\x00b", "tail"],
}
assert struct_optional_lists.echo(value) == value

for bad in [
    {**value, "narrow": [256]},
    {**value, "flags": [1]},
    {**value, "signed": [1.5]},
    {**value, "labels": ["ok\x00bad"]},
]:
    try:
        struct_optional_lists.echo(bad)
    except (OverflowError, TypeError, ValueError):
        pass
    else:
        raise AssertionError("invalid optional struct list element was accepted")
print("pymodule struct-optional-list smoke OK")
PY
