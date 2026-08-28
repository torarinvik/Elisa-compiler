#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$(command -v clang || true)" ]]; then
    echo "pymodule struct-set smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
# Struct set fields copy the incoming iterable before hashing. Keep the transformed failure path
# responsible for releasing that owned copy as well as the shared arena.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/struct_sets.c" "$ROOT/test/repro/pymodule_struct_sets.elisa" >/dev/null
grep -Fq 'Py_XDECREF(arg0_owned); Py_DECREF(field_obj); return -1;' "$WORK/struct_sets.c"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_sets.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_sets.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_sets

value = {"numbers": {-2, 4, 11}, "labels": {"first", "second"}, "views": {"embedded\x00nul", "unicode-λ"}}
echoed = struct_sets.echo(value)
assert echoed["numbers"] == value["numbers"]
assert echoed["labels"] == value["labels"]
assert echoed["views"] == value["views"]
empty = struct_sets.echo({"numbers": set(), "labels": set(), "views": set()})
assert empty == {"numbers": set(), "labels": set(), "views": set()}

for bad in [
    {**value, "numbers": {1.5}},
    {**value, "labels": {"embedded\x00nul"}},
    {**value, "views": {1}},
]:
    try:
        struct_sets.echo(bad)
    except (OverflowError, TypeError, ValueError):
        pass
    else:
        raise AssertionError("invalid struct set value was accepted")
print("pymodule struct-set smoke OK")
PY
