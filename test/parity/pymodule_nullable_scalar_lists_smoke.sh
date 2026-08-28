#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable-scalar-list smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/nullable_scalar_lists.json" \
    "$ROOT/test/repro/pymodule_nullable_scalar_lists.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/nullable_scalar_lists.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
assert [row["parameters"][0]["type"] for row in manifest["functions"]] == [
    "darray[i64?]", "darray[u8?]", "darray[bool?]", "darray[f32?]"
]
assert [row["return"] for row in manifest["functions"]] == [
    "darray[i64?]", "darray[u8?]", "darray[bool?]", "darray[f32?]"
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nullable_scalar_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_nullable_scalar_lists.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nullable_scalar_lists

assert nullable_scalar_lists.optional_signed([-2, None, 7]) == [-2, None, 7]
assert nullable_scalar_lists.optional_unsigned([0, None, 255]) == [0, None, 255]
assert nullable_scalar_lists.optional_bool([True, None, False]) == [True, None, False]
floats = nullable_scalar_lists.optional_float([1.25, None, -2.5])
assert floats[0] == 1.25 and floats[1] is None and abs(floats[2] + 2.5) < 1e-6
for value in ([256], [-1]):
    try:
        nullable_scalar_lists.optional_unsigned(value)
    except OverflowError:
        pass
    else:
        raise AssertionError("nullable u8 list range check missing")
try:
    nullable_scalar_lists.optional_signed(["bad"])
except TypeError:
    pass
else:
    raise AssertionError("nullable integer list should reject text")
PY

echo "pymodule nullable-scalar-list smoke OK"
