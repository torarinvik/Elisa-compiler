#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule view struct aggregate smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

if nm -u "$ROOT/build/runtime/elisacore_runtime.o" 2>/dev/null | grep -q 'elisa_native_callback_'; then
    echo "pymodule view struct aggregate smoke SKIP (runtime callback host unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/view_struct_aggregate.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_view_struct_aggregate.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import view_struct_aggregate

values = [
    {"x": 1, "tags": [2, 3], "attrs": {4: 5}},
    {"x": -1, "tags": [], "attrs": {}},
]
assert view_struct_aggregate.roundtrip(values) == values

for bad in (
    [{"x": "bad", "tags": [], "attrs": {}}],
    [{"x": 1, "tags": ["bad"], "attrs": {}}],
    [{"x": 1, "tags": [], "attrs": {"bad": 2}}],
):
    try:
        view_struct_aggregate.roundtrip(bad)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid aggregate view struct accepted")

print("pymodule view struct aggregate smoke OK")
PY
