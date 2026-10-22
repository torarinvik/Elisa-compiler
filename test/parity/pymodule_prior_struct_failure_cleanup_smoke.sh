#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"

SOURCE="$ROOT/test/repro/pymodule_prior_struct_failure_cleanup.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/prior_struct_failure_cleanup.c" "$SOURCE" >/dev/null
python3 - "$WORK/prior_struct_failure_cleanup.c" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()
marker = "static PyObject *elisa_py_bad_struct_before_darray("
start = source.index(marker)
next_wrapper = source.find("static PyObject *elisa_py_", start + len(marker))
wrapper = source[start:next_wrapper if next_wrapper >= 0 else len(source)]
failure_marker = "if (arg1_seq == NULL) {"
failure_start = wrapper.index(failure_marker)
open_brace = wrapper.index("{", failure_start)
depth = 0
for index in range(open_brace, len(wrapper)):
    if wrapper[index] == "{":
        depth += 1
    elif wrapper[index] == "}":
        depth -= 1
        if depth == 0:
            failure = wrapper[failure_start:index]
            break
else:
    raise AssertionError("unterminated generated darray failure branch")
assert "elisa_pymodule_struct_ObjectBatch_free(&arg0_value);" in failure, "later darray failure does not release the converted struct argument"
PY

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule prior struct failure cleanup smoke generated-C checks OK (runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/prior_struct_failure_cleanup.cpython-314-darwin.so" \
    "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import gc
import weakref

import prior_struct_failure_cleanup as module

class Marker:
    pass

def expect_type_error(batch, values):
    try:
        module.bad_struct_before_darray(batch, values)
    except TypeError:
        return
    raise AssertionError("invalid darray argument unexpectedly converted")

for _ in range(1000):
    marker = Marker()
    reference = weakref.ref(marker)
    batch = {"values": [marker]}
    expect_type_error(batch, object())
    del batch, marker
    gc.collect()
    assert reference() is None, "struct conversion retained a Python object after later darray failure"

marker = Marker()
assert module.bad_struct_before_darray({"values": [marker]}, [1, 2]) == 2
print("pymodule prior struct failure cleanup smoke OK")
PY
