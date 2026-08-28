#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule C smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE_DIR="$WORK/nested/generated"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$SOURCE_DIR/fastmath.c" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -o "$SOURCE_DIR/fastmath.o" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null

"$CLANG" -bundle -undefined dynamic_lookup $("$PYTHON_CONFIG" --includes) \
    -o "$WORK/fastmath.cpython-314-darwin.so" "$SOURCE_DIR/fastmath.c" "$SOURCE_DIR/fastmath.o" \
    "$ROOT/build/runtime/elisacore_runtime.o"

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import fastmath
assert fastmath.add(2, 3) == 5
assert fastmath.negate(False) is True
assert fastmath.negate(True) is False
assert fastmath.ping() == 42
PY

echo "pymodule C smoke OK"
