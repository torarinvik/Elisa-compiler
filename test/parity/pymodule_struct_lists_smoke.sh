#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct lists smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_lists.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_lists
from types import SimpleNamespace

assert struct_lists.shape({"values": [1, 2], "weights": [0.5], "flags": [True, False]}) == 5
assert struct_lists.shape(SimpleNamespace(values=(), weights=(1.0, 2.0), flags=[False])) == 3

for bad in [
    {"values": [1.5], "weights": [], "flags": []},
    {"values": [1], "weights": [1.0], "flags": [1]},
    {"values": [2**70], "weights": [], "flags": []},
]:
    try:
        struct_lists.shape(bad)
    except (OverflowError, TypeError):
        pass
    else:
        raise AssertionError("invalid struct list element was accepted")

try:
    struct_lists.shape({"values": [2**70], "weights": [], "flags": []})
except OverflowError as exc:
    assert "at path .values[0]:" in str(exc)
    assert exc.function == "shape"
    assert exc.parameter == "batch"
    assert exc.path == ".values[0]"
else:
    raise AssertionError("struct list error did not include field and element paths")

print("pymodule struct lists smoke OK")
PY
