#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"

SOURCE="$ROOT/test/repro/pymodule_prior_darray_failure_cleanup.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/prior_darray_failure_cleanup.c" "$SOURCE" >/dev/null
python3 - "$WORK/prior_darray_failure_cleanup.c" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()

def wrapper(function_name):
    marker = f"static PyObject *elisa_py_{function_name}("
    start = source.index(marker)
    next_wrapper = source.find("static PyObject *elisa_py_", start + len(marker))
    return source[start:next_wrapper if next_wrapper >= 0 else len(source)]

def failure_branch(function_source, marker):
    start = function_source.index(marker)
    open_brace = function_source.index("{", start)
    depth = 0
    for index in range(open_brace, len(function_source)):
        if function_source[index] == "{":
            depth += 1
        elif function_source[index] == "}":
            depth -= 1
            if depth == 0:
                return function_source[start:index]
    raise AssertionError(f"unterminated generated failure branch: {marker}")

def aggregate_cleanup(function_source, function_name):
    assert "goto elisa_pymodule_aggregate_inputs_error;" in function_source, f"{function_name} has no shared cleanup jump"
    cleanup_start = function_source.index("elisa_pymodule_aggregate_inputs_error:")
    cleanup_end = function_source.index("return NULL;", cleanup_start)
    return function_source[cleanup_start:cleanup_end]

set_wrapper = wrapper("bad_set_after_darray")
set_failure = failure_branch(set_wrapper, "if (arg1_owned == NULL) {")
assert "goto elisa_pymodule_aggregate_inputs_error;" in set_failure, "set conversion failure bypasses shared cleanup"
dict_wrapper = wrapper("bad_dict_after_darray")
dict_failure = failure_branch(dict_wrapper, "if (!PyMapping_Check(arg1)) {")
assert "goto elisa_pymodule_aggregate_inputs_error;" in dict_failure, "dict conversion failure bypasses shared cleanup"
for marker in (
    "if (arg1_dict_len < 0) {",
    "if (arg1_dict_len > PY_SSIZE_T_MAX / 2) {",
    "if (arg1_buckets == NULL) {",
):
    branch = failure_branch(dict_wrapper, marker)
    assert "arg1_materialized = 0;" in branch, f"{marker} leaves the dict marked materialized before shared cleanup"
    assert "arg1 = NULL;" in branch, f"{marker} leaves a freed dict pointer visible to shared cleanup"
    assert "Py_XDECREF(elisa_cleanup_owned_arg1);" in branch, f"{marker} does not transfer dict reference ownership to local cleanup"
    assert "goto elisa_pymodule_aggregate_inputs_error;" in branch, f"{marker} bypasses shared cleanup"
later_set_wrapper = wrapper("bad_dict_after_later_set")
later_set_failure = failure_branch(later_set_wrapper, "if (!PyMapping_Check(arg1)) {")
assert "goto elisa_pymodule_aggregate_inputs_error;" in later_set_failure, "dict failure after later set bypasses shared cleanup"
fixed_array_dict_wrapper = wrapper("bad_dict_after_fixed_array")
fixed_array_dict_failure = failure_branch(fixed_array_dict_wrapper, "if (!PyMapping_Check(arg1)) {")
assert "goto elisa_pymodule_aggregate_inputs_error;" in fixed_array_dict_failure, "dict failure after fixed-array conversion bypasses shared cleanup"
fixed_array_set_wrapper = wrapper("bad_set_after_fixed_array")
fixed_array_set_failure = failure_branch(fixed_array_set_wrapper, "if (arg1_owned == NULL) {")
assert "goto elisa_pymodule_aggregate_inputs_error;" in fixed_array_set_failure, "set failure after fixed-array conversion bypasses shared cleanup"
fixed_array_after_darray_wrapper = wrapper("bad_fixed_array_after_darray")
fixed_array_after_darray_failure = failure_branch(fixed_array_after_darray_wrapper, "if (PySequence_Fast_GET_SIZE(arg1_seq) != 4) {")
assert "Py_XDECREF(arg0_seq); arg0_seq = NULL;" in fixed_array_after_darray_failure, "fixed-array conversion failure does not release the prior darray sequence"
assert "Py_XDECREF(arg1_seq); arg1_seq = NULL;" in fixed_array_after_darray_failure, "fixed-array conversion failure does not release its own sequence"
assert "Py_XDECREF(arg2_default); arg2_default = NULL;" in fixed_array_after_darray_failure, "fixed-array conversion failure does not release the omitted optional default"
fixed_array_alias_wrapper = wrapper("bad_fixed_array_alias_after_darray")
fixed_array_alias_failure = failure_branch(fixed_array_alias_wrapper, "if (PySequence_Fast_GET_SIZE(arg1_seq) != 4) {")
assert "Py_XDECREF(arg0_seq); arg0_seq = NULL;" in fixed_array_alias_failure, "fixed-array alias conversion failure does not release the prior darray sequence"
assert "Py_XDECREF(arg1_seq); arg1_seq = NULL;" in fixed_array_alias_failure, "fixed-array alias conversion failure does not release its own sequence"
assert "Py_XDECREF(arg2_default); arg2_default = NULL;" in fixed_array_alias_failure, "fixed-array alias conversion failure does not release the omitted optional default"

for function_name, function_source, default_index in (
    ("set", set_wrapper, 2),
    ("dict", dict_wrapper, 2),
    ("dict after later set", later_set_wrapper, 3),
):
    cleanup = aggregate_cleanup(function_source, function_name)
    assert "Py_XDECREF(arg0_seq); arg0_seq = NULL;" in cleanup, f"{function_name} failure does not release the prior darray sequence"
    assert "PyMem_Free(arg0_items); arg0_items = NULL;" in cleanup, f"{function_name} failure does not free the prior darray buffer"
    assert f"Py_XDECREF(arg{default_index}_default); arg{default_index}_default = NULL;" in cleanup, f"{function_name} failure does not release the omitted optional default"
later_set_cleanup = aggregate_cleanup(later_set_wrapper, "dict after later set")
assert "if (arg2_materialized)" in later_set_cleanup, "dict failure does not release a later set already materialized in Stage 4"
assert "arena_free(&arg2_arena); Py_XDECREF(elisa_cleanup_owned_arg2);" in later_set_cleanup, "dict failure does not free the later set arena and Python object"
for function_name, function_source in (
    ("dict after fixed array", fixed_array_dict_wrapper),
    ("set after fixed array", fixed_array_set_wrapper),
):
    cleanup = aggregate_cleanup(function_source, function_name)
    assert "Py_XDECREF(arg0_seq); arg0_seq = NULL;" in cleanup, f"{function_name} failure does not release the fixed-array sequence"
    assert "arg0_items" not in cleanup, f"{function_name} cleanup unexpectedly references heap-backed darray storage"
    assert "Py_XDECREF(arg2_default); arg2_default = NULL;" in cleanup, f"{function_name} failure does not release the omitted optional default"
PY

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule prior darray failure cleanup smoke generated-C checks OK (runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/prior_darray_failure_cleanup.cpython-314-darwin.so" \
    "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import gc
import tracemalloc

import prior_darray_failure_cleanup as module

assert module.bad_dict_after_darray([1, 2], {3: 4}) == 1234567890123456789
assert module.bad_dict_after_darray([1], {2: 3}, maybe=11) == 11
assert module.bad_set_after_darray([1, 2], {3}) == 1234567890123456789
assert module.bad_set_after_darray([1], {2}, maybe=11) == 11
assert module.bad_dict_after_later_set([1, 2], {3: 4}, {5}) == 1234567890123456789
assert module.bad_dict_after_later_set([1], {2: 3}, {4}, maybe=11) == 11
assert module.bad_dict_after_fixed_array([1, 2, 3, 4], {5: 6}) == 1234567890123456789
assert module.bad_dict_after_fixed_array([1, 2, 3, 4], {5: 6}, maybe=11) == 11
assert module.bad_set_after_fixed_array((1, 2, 3, 4), {5}) == 1234567890123456789
assert module.bad_set_after_fixed_array((1, 2, 3, 4), {5}, maybe=11) == 11
assert module.bad_fixed_array_after_darray([1, 2, 3, 4], [5, 6, 7, 8]) == 1234567890123456789
assert module.bad_fixed_array_after_darray([1], [5, 6, 7, 8], maybe=11) == 11
assert module.bad_fixed_array_alias_after_darray([1, 2, 3, 4], [5, 6, 7, 8]) == 1234567890123456789
assert module.bad_fixed_array_alias_after_darray([1], [5, 6, 7, 8], maybe=11) == 11

def expect_type_error(call):
    try:
        call()
    except TypeError:
        return
    raise AssertionError("invalid dict/set argument unexpectedly converted")

gc.collect()
tracemalloc.start()
before, _ = tracemalloc.get_traced_memory()
for _ in range(3000):
    expect_type_error(lambda: module.bad_dict_after_darray([1, 2, 3, 4], object()))
    expect_type_error(lambda: module.bad_set_after_darray([1, 2, 3, 4], object()))
    expect_type_error(lambda: module.bad_dict_after_later_set([1, 2, 3, 4], object(), {5, 6}))
    expect_type_error(lambda: module.bad_dict_after_fixed_array(range(4), object()))
    expect_type_error(lambda: module.bad_set_after_fixed_array(range(4), object()))
    try:
        module.bad_fixed_array_after_darray([1, 2, 3, 4], [5])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid fixed-array length unexpectedly converted")
    try:
        module.bad_fixed_array_alias_after_darray([1, 2, 3, 4], [5])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid fixed-array alias length unexpectedly converted")
    assert module.bad_dict_after_fixed_array(range(4), {5: 6}) == 1234567890123456789
    assert module.bad_set_after_fixed_array(range(4), {5}) == 1234567890123456789
gc.collect()
after, _ = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert after - before < 65536, f"darray/default inputs leaked across dict/set failures: {after - before} bytes"
PY

echo "pymodule prior darray failure cleanup smoke OK"
