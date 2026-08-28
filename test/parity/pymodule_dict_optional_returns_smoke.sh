#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict-optional-returns smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/dict_optional_returns.json" \
    "$ROOT/test/repro/pymodule_dict_optional_returns.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/dict_optional_returns.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    rows = {row["name"]: row for row in json.load(handle)["functions"]}
assert rows["maybe_count"]["parameters"] == [{"name": "values", "type": "dict[i64,i64]"}]
assert rows["maybe_count"]["return"] == "i64?"
assert rows["text_from_dict"]["return"] == "cstr"
assert rows["view_from_dict"]["return"] == "sview"
assert rows["object_from_dict"]["return"] == "py::Object"
assert rows["nullable_text_from_dict"]["return"] == "cstr?"
assert rows["list_from_dict"]["parameters"] == [
    {"name": "values", "type": "dict[i64,i64]"},
    {"name": "items", "type": "darray[i64]"},
]
assert rows["list_from_dict"]["return"] == "darray[i64]"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/dict_optional_returns.c" \
    "$ROOT/test/repro/pymodule_dict_optional_returns.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/dict_optional_returns.c" <<'PY'
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    source = handle.read()

cleanup = "arena_free(&arg0_arena); Py_DECREF(arg0);"
for name in ("text_from_dict", "view_from_dict", "object_from_dict", "nullable_text_from_dict", "list_from_dict"):
    start = source.index(f"static PyObject *elisa_py_{name}")
    next_wrapper = source.find("\nstatic PyObject *elisa_py_", start + 1)
    body = source[start:] if next_wrapper < 0 else source[start:next_wrapper]
    native_call = body.index(f"elisa_pymodule_dict_optional_returns_{name}")
    assert cleanup in body[native_call:], name
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_optional_returns.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_dict_optional_returns.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_optional_returns

assert dict_optional_returns.maybe_count({}) is None
assert dict_optional_returns.maybe_count({1: 2, 3: 4}) == 2
assert dict_optional_returns.maybe_count(values={9: 1}) == 1
assert dict_optional_returns.text_from_dict({}) == "ok"
assert dict_optional_returns.text_from_dict({1: 2}) == "ok"
assert dict_optional_returns.view_from_dict({}) == "ok"
assert dict_optional_returns.view_from_dict({1: 2}) == "ok"
value = {"payload": True}
assert dict_optional_returns.object_from_dict({}, value) is value
assert dict_optional_returns.object_from_dict({1: 2}, value=value) is value
assert dict_optional_returns.nullable_text_from_dict({}) is None
assert dict_optional_returns.nullable_text_from_dict({1: 2}) == "ok"
assert dict_optional_returns.list_from_dict({}, [1, 2, 3]) == [1, 2, 3]
assert dict_optional_returns.list_from_dict({1: 2}, items=[4, 5]) == [4, 5]
PY

echo "pymodule dict-optional-returns smoke OK"
