#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/type_aliases.json" \
    "$ROOT/test/repro/pymodule_type_aliases.elisa" >/dev/null
python3 - "$WORK/type_aliases.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
rows = {row["name"]: row for row in manifest["functions"]}
assert rows["identity_id"]["parameters"] == [{"name": "value", "type": "i64"}]
assert rows["identity_id"]["return"] == "i64"
assert rows["identity_count"]["parameters"] == [{"name": "value", "type": "u8"}]
assert rows["identity_count"]["return"] == "u8"
assert rows["identity_name"]["parameters"] == [{"name": "value", "type": "sview"}]
assert rows["identity_name"]["return"] == "sview"
assert rows["identity_optional"]["parameters"] == [{"name": "value", "type": "i64?", "default": "None"}]
assert rows["identity_optional"]["return"] == "i64?"
assert rows["identity_ids"]["parameters"] == [{"name": "values", "type": "darray[i64]"}]
assert rows["identity_ids"]["return"] == "darray[i64]"
assert rows["identity_map"]["parameters"] == [{"name": "values", "type": "dict[cstr,i64]"}]
assert rows["identity_map"]["return"] == "dict[cstr,i64]"
PY

GENERATED_C="$WORK/type_aliases.c"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$GENERATED_C" \
    "$ROOT/test/repro/pymodule_type_aliases.elisa" >/dev/null
python3 - "$GENERATED_C" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text()

def wrapper(name):
    marker = f"static PyObject *elisa_py_{name}("
    start = source.index(marker)
    next_wrapper = source.find("static PyObject *elisa_py_", start + len(marker))
    return source[start:next_wrapper if next_wrapper >= 0 else len(source)]

def failure_branch(function_source, trigger):
    start = function_source.index(trigger)
    open_brace = function_source.index("{", start)
    depth = 0
    quote = None
    escaped = False
    for index in range(open_brace, len(function_source)):
        character = function_source[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ('"', "'"):
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return function_source[start:index]
    raise AssertionError(f"unterminated generated failure branch: {trigger}")

def assert_cleanup_in_failure_branch(name, trigger, fragments):
    body = wrapper(name)
    branch = failure_branch(body, trigger)
    position = 0
    for fragment in fragments:
        position = branch.find(fragment, position)
        assert position >= 0, f"{name} failure branch {trigger!r} is missing {fragment!r}"
        position += len(fragment)

assert_cleanup_in_failure_branch(
    "fail_after_alias_list",
    "if (arg1_number > UINT8_MAX)",
    (
        "Py_XDECREF(arg0_seq); arg0_seq = NULL;",
        "PyMem_Free(arg0_items); arg0_items = NULL;",
        "elisa_pymodule_struct_refs_free(&arg0_struct_refs);",
        "arena_free(&arg0_struct_arena);",
    ),
)
assert_cleanup_in_failure_branch(
    "fail_after_nested_alias_list",
    "if (arg1_number > UINT8_MAX)",
    (
        "elisa_pymodule_struct_refs_free(&arg0_struct_refs);",
        "arena_free(&arg0_struct_arena);",
    ),
)
assert_cleanup_in_failure_branch(
    "fail_after_alias_dict",
    "if (!PyMapping_Check(arg1))",
    (
        "elisa_pymodule_struct_refs_free(&arg0_struct_refs);",
        "arena_free(&arg0_arena);",
        "Py_XDECREF(elisa_cleanup_owned_arg0);",
    ),
)
PY

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule type-alias smoke generated-C checks OK (runtime build unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/type_aliases.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_type_aliases.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import gc
import type_aliases
import tracemalloc

assert type_aliases.identity_id(42) == 42
assert type_aliases.identity_count(255) == 255
assert type_aliases.identity_name("på\x00東京") == "på\x00東京"
assert type_aliases.identity_optional() is None
assert type_aliases.identity_optional(7) == 7
assert type_aliases.identity_ids([1, 2, 3]) == [1, 2, 3]
assert type_aliases.identity_map({"first": 1, "second": 2}) == {"first": 1, "second": 2}

# A later list range failure must release aliased darray and dict inputs, including the
# Python references and arena allocated for a named-struct element.
gc.collect()
tracemalloc.start()
before, _ = tracemalloc.get_traced_memory()
for _ in range(3000):
    for function, value, later_value, error_type in (
        (type_aliases.fail_after_alias_list, [{"label": "point"}], [256], OverflowError),
        (type_aliases.fail_after_nested_alias_list, [[{"label": "point"}]], [256], OverflowError),
        (type_aliases.fail_after_alias_dict, {"first": {"label": "point"}}, object(), TypeError),
    ):
        try:
            function(value, later_value)
        except error_type:
            pass
        else:
            raise AssertionError(f"{function.__name__} accepted an invalid later container")
gc.collect()
after, _ = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert after - before < 65536, (
    f"aliased container inputs leaked after a later conversion failure: {after - before} bytes"
)

try:
    type_aliases.identity_count(256)
except OverflowError:
    pass
else:
    raise AssertionError("u8 alias should retain narrow range checking")

print("pymodule type-alias smoke OK")
PY
