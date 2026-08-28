#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule darray dictionary error payload smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_error_payload_darray_dict.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
function = manifest["functions"][0]
assert function["parameters"] == [{"name": "values", "type": "darray[dict[i64,i64]]"}]
assert function["payload"] == "darray[dict[i64,i64]]"
struct_function = manifest["functions"][1]
assert struct_function["parameters"] == [{"name": "values", "type": "darray[dict[i64,Point]]"}]
assert struct_function["payload"] == "darray[dict[i64,Point]]"
nested_function = manifest["functions"][2]
assert nested_function["parameters"] == [{"name": "values", "type": "darray[dict[i64,darray[dict[cstr,i64]]]]"}]
assert nested_function["payload"] == "darray[dict[i64,darray[dict[cstr,i64]]]]"
PY

# Aggregate payload conversion happens before ordinary input cleanup. Its failure label must
# release the payload object and funnel through the wrapper's ownership cleanup instead of
# returning directly from generated wrapper code.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/error_payload_darray_dict.c" "$SOURCE" >/dev/null
grep -Fq 'elisa_pymodule_error_payload_conversion_failed:' "$WORK/error_payload_darray_dict.c"
grep -Fq 'Py_XDECREF(native_payload_object);' "$WORK/error_payload_darray_dict.c"
grep -Fq 'goto elisa_pymodule_error_payload_conversion_failed;' "$WORK/error_payload_darray_dict.c"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_darray_dict.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_darray_dict as module
import sys

rows = [{1: 2, 3: -4}, {}, {9: 10}]
try:
    module.fail_rows(rows)
except module.RowsPayloadError as exc:
    assert exc.function == "fail_rows"
    assert exc.payload == rows
else:
    raise AssertionError("expected RowsPayloadError")

# Error payload conversion must not retain the borrowed top-level sequence after
# copying it into the exception payload.  This used to leak one list reference per
# raised aggregate error.
rows_refcount = sys.getrefcount(rows)
for _ in range(100):
    try:
        module.fail_rows(rows)
    except module.RowsPayloadError:
        pass
assert sys.getrefcount(rows) == rows_refcount

try:
    module.fail_rows([{1: 2**80}])
except OverflowError:
    pass
else:
    raise AssertionError("dictionary value range check was lost in error payload")

struct_rows = [{1: {"x": 2, "label": "a\x00b"}}, {}]
try:
    module.fail_struct_rows(struct_rows)
except module.StructRowsPayloadError as exc:
    assert exc.payload == struct_rows
else:
    raise AssertionError("expected StructRowsPayloadError")

nested_rows = [{4: [{"x": 7}, {}]}, {}]
try:
    module.fail_nested_rows(nested_rows)
except module.NestedRowsPayloadError as exc:
    assert exc.payload == nested_rows
else:
    raise AssertionError("expected NestedRowsPayloadError")

print("pymodule darray dictionary error payload smoke OK")
PY
