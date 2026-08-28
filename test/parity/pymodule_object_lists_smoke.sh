#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [ ! -x "$PYTHON_BIN" ] || [ ! -x "$PYTHON_CONFIG" ] || [ ! -x "$CLANG" ] || [ ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]; then
    echo "pymodule object-list smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

SO="$TMP/object_lists.cpython-314-darwin.so"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so -o "$SO" "$ROOT/test/repro/pymodule_object_list.elisa"

PYTHONPATH="$TMP" "$PYTHON_BIN" - <<'PY'
import importlib

mod = importlib.import_module("object_lists")
first = {"kind": "mapping"}
second = [1, 2, 3]
assert mod.count([first, second, None]) == 3
out = mod.echo([first, second, None])
assert out[0] is first
assert out[1] is second
assert out[2] is None
print("pymodule object-list smoke OK")
PY
