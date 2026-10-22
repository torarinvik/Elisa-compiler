#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional range cleanup smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_optional_range_cleanup.elisa"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_range_cleanup.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import gc
import tracemalloc

import optional_range_cleanup as module

assert module.optional_then_narrow() == 1234567890123456789
assert module.optional_then_narrow(narrow=255) == 1234567890123456789
assert module.aliased_optional_then_narrow() == 1234567890123456789
assert module.aliased_optional_then_narrow(narrow=255) == 1234567890123456789

# The omitted nullable default is materialized before the later u8 range check fails.
gc.collect()
tracemalloc.start()
before, _ = tracemalloc.get_traced_memory()
for _ in range(3000):
    try:
        module.optional_then_narrow(narrow=256)
    except OverflowError:
        pass
    else:
        raise AssertionError("out-of-range u8 value unexpectedly converted")
for _ in range(3000):
    try:
        module.aliased_optional_then_narrow(narrow=256)
    except OverflowError:
        pass
    else:
        raise AssertionError("out-of-range u8 value unexpectedly converted for optional alias")
gc.collect()
after, _ = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert after - before < 65536, f"nullable defaults leaked across scalar range failures: {after - before} bytes"
PY

echo "pymodule optional range cleanup smoke OK"
