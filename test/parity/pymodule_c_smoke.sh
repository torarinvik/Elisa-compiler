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
    echo "pymodule C smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE_DIR="$WORK/nested/generated"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$SOURCE_DIR/fastmath.c" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null
bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -o "$SOURCE_DIR/fastmath.o" \
    "$ROOT/test/repro/pymodule_export.elisa" >/dev/null

"$CLANG" $ELISA_SHARED_MODULE_FLAGS -fno-builtin $("$PYTHON_CONFIG" --includes) \
    -o "$WORK/fastmath$("$PYTHON_BIN" -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")" "$SOURCE_DIR/fastmath.c" "$SOURCE_DIR/fastmath.o" \
    "$ROOT/build/runtime/elisacore_runtime.o" "$ROOT/scripts/pymodule_runtime_fallback.c"

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import fastmath
assert fastmath.add(2, 3) == 5
assert fastmath.negate(False) is True
assert fastmath.negate(True) is False
assert fastmath.ping() == 42
PY

echo "pymodule C smoke OK"
