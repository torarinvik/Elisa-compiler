#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct field list smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_field_list.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_field_list.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_field_list

value = {"list": [1, 2, 3]}
assert struct_field_list.roundtrip(value) == value
print("pymodule struct field list smoke OK")
PY
