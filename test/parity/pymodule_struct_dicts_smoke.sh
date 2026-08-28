#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$(command -v clang || true)" ]]; then
    echo "pymodule struct-dict smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
# Struct-field mappings receive a copied Python dict before conversion. The generated helper must
# release that owned copy on every transformed failure path, including arena allocation errors.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/struct_dicts.c" "$ROOT/test/repro/pymodule_struct_dicts.elisa" >/dev/null
grep -Fq 'Py_XDECREF(arg0_owned); Py_DECREF(field_obj); return -1;' "$WORK/struct_dicts.c"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_dicts.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_dicts.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_dicts

first = {"name": "first"}
value = {
    "numbers": {-2: 7, 4: 11},
    "nested": {"odd": [1, 3, 5], "empty": []},
    "objects": {"first": first, "missing": None},
}
echoed = struct_dicts.echo(value)
assert echoed["numbers"] == value["numbers"]
assert echoed["nested"] == value["nested"]
assert echoed["objects"]["first"] is first
assert echoed["objects"]["missing"] is None

for bad in [
    {**value, "numbers": {1.5: 2}},
    {**value, "nested": {"bad": [2**70]}},
]:
    try:
        struct_dicts.echo(bad)
    except (OverflowError, TypeError):
        pass
    else:
        raise AssertionError("invalid struct dictionary value was accepted")
print("pymodule struct-dict smoke OK")
PY
