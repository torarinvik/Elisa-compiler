#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional-scalar smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/optional_scalar.json" \
    "$ROOT/test/repro/pymodule_optional_scalar.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/optional_scalar.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert [row["parameters"][0]["type"] for row in manifest["functions"]] == [
    "i64?", "f64?", "bool?", "i8?", "u8?", "i32?", "f32?"
]
assert all(row["parameters"][0]["default"] == "None" for row in manifest["functions"])
assert [row["return"] for row in manifest["functions"]] == [
    "i64?", "f64?", "bool?", "i8?", "u8?", "i32?", "f32?"
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_scalar.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_optional_scalar.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import optional_scalar

assert optional_scalar.maybe_int() is None
assert optional_scalar.maybe_int(None) is None
assert optional_scalar.maybe_int(value=-42) == -42
assert optional_scalar.maybe_float(1.25) == 1.25
assert optional_scalar.maybe_bool(False) is False
assert optional_scalar.maybe_bool(True) is True
assert optional_scalar.maybe_i8(127) == 127
assert optional_scalar.maybe_u8(255) == 255
assert optional_scalar.maybe_i32(-123) == -123
assert abs(optional_scalar.maybe_f32(1.5) - 1.5) < 1e-6
assert str(inspect.signature(optional_scalar.maybe_int)) == "(value=None)"

for function, value in ((optional_scalar.maybe_i8, 128), (optional_scalar.maybe_u8, -1)):
    try:
        function(value)
    except OverflowError:
        pass
    else:
        raise AssertionError("narrow optional integer should range-check")
PY

echo "pymodule optional-scalar smoke OK"
