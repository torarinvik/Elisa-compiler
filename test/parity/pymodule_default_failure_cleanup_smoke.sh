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
    echo "pymodule default failure cleanup smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/default_failure_cleanup.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_default_failure_cleanup.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import gc
import tracemalloc

import default_failure_cleanup as module

assert module.bad_dict_before_optional() == 1234567890123456789
assert module.bad_set_before_optional() == 1234567890123456789

def expect_type_error(call):
    try:
        call()
    except TypeError:
        return
    raise AssertionError("invalid aggregate argument unexpectedly converted")

gc.collect()
tracemalloc.start()
before, _ = tracemalloc.get_traced_memory()
for _ in range(3000):
    expect_type_error(lambda: module.bad_dict_before_optional(mapping=object()))
    expect_type_error(lambda: module.bad_set_before_optional(values=object()))
gc.collect()
after, _ = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert after - before < 65536, f"nullable defaults leaked across dict/set setup failures: {after - before} bytes"
PY

echo "pymodule default failure cleanup smoke OK"
