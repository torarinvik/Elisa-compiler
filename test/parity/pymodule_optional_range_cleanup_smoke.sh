#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
SOURCE="$ROOT/test/repro/pymodule_optional_range_cleanup.elisa"
GENERATED_C="$WORK/optional_range_cleanup.c"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$GENERATED_C" "$SOURCE" >/dev/null
python3 - "$GENERATED_C" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()

def wrapper(name):
    marker = f"static PyObject *elisa_py_{name}("
    start = source.index(marker)
    next_wrapper = source.find("static PyObject *elisa_py_", start + len(marker))
    return source[start:next_wrapper if next_wrapper >= 0 else len(source)]

for name in ("optional_then_narrow", "aliased_optional_then_narrow"):
    body = wrapper(name)
    range_guard = body.index("if (arg1 > UINT8_MAX)")
    cleanup = body.find("Py_XDECREF(arg0_default); arg0_default = NULL;", range_guard)
    assert cleanup >= 0, (
        f"{name} does not release the omitted optional default after the later u8 range failure"
    )

body = wrapper("aliased_optional_then_bad_dict")
mapping_guard = body.index("if (!PyMapping_Check(arg1))")
cleanup = body.find("Py_XDECREF(arg0_default); arg0_default = NULL;", mapping_guard)
assert cleanup >= 0, (
    "aliased_optional_then_bad_dict does not release the omitted optional default after dict setup fails"
)

body = wrapper("borrowed_default_cstr")
copy_result = body.index("PyObject *out = result == NULL ? NULL : PyUnicode_FromString(result);")
cleanup = body.find("Py_XDECREF(arg0_default); arg0_default = NULL;", copy_result)
assert cleanup > copy_result, (
    "borrowed_default_cstr releases its omitted cstr? default before copying the returned text"
)

body = wrapper("borrowed_default_sview")
optional_length_guard = body.index("else if (result.value.len < 0 || result.value.len > PY_SSIZE_T_MAX")
optional_decode = body.index("PyUnicode_DecodeUTF8(result.value.data, (Py_ssize_t)result.value.len")
assert optional_length_guard < optional_decode, (
    "borrowed_default_sview casts an oversized length before checking PY_SSIZE_T_MAX"
)
copy_result = body.index("PyUnicode_DecodeUTF8(result.value.data")
cleanup = body.find("Py_XDECREF(arg0_default); arg0_default = NULL;", copy_result)
assert cleanup > copy_result, (
    "borrowed_default_sview releases its omitted sview? default before copying the returned text"
)

body = wrapper("borrowed_default_plain_sview")
direct_length_guard = body.index("if (result.len < 0 || result.len > PY_SSIZE_T_MAX)")
direct_decode = body.index("PyUnicode_DecodeUTF8(result.data, (Py_ssize_t)result.len")
assert direct_length_guard < direct_decode, (
    "borrowed_default_plain_sview casts an oversized length before checking PY_SSIZE_T_MAX"
)
copy_result = direct_decode
cleanup = body.find("Py_XDECREF(arg0_default); arg0_default = NULL;", copy_result)
assert cleanup > copy_result, (
    "borrowed_default_plain_sview releases its omitted sview default before copying the returned text"
)
PY

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional range cleanup smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

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
assert module.aliased_optional_then_bad_dict() == 1234567890123456789
assert module.borrowed_default_cstr() == "borrowed return default"
assert module.borrowed_default_plain_sview() == "borrowed direct sview return default"
assert module.borrowed_default_sview() == "borrowed optional sview return default"

# The omitted nullable default is materialized before the later u8 range check fails.
gc.collect()
tracemalloc.start()
before, _ = tracemalloc.get_traced_memory()
for _ in range(3000):
    assert module.optional_then_narrow() == 1234567890123456789
    assert module.aliased_optional_then_narrow() == 1234567890123456789
    assert module.aliased_optional_then_bad_dict() == 1234567890123456789
    assert module.borrowed_default_cstr() == "borrowed return default"
    assert module.borrowed_default_plain_sview() == "borrowed direct sview return default"
    assert module.borrowed_default_sview() == "borrowed optional sview return default"
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
for _ in range(3000):
    try:
        module.aliased_optional_then_bad_dict(values=object())
    except TypeError:
        pass
    else:
        raise AssertionError("non-mapping dict value unexpectedly converted")
gc.collect()
after, _ = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert after - before < 65536, f"nullable defaults leaked across scalar or dict setup failures: {after - before} bytes"
PY

echo "pymodule optional range cleanup smoke OK"
