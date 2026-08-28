#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule errors smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/errors.json" \
    "$ROOT/test/repro/pymodule_errors.elisa" >/dev/null
python3 - "$WORK/errors.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["divide"]["raises"] == "DivideError"
assert functions["checked_list_payload"]["raises"] == "ListPayloadError"
assert functions["checked_list_payload"]["payload"] == "i64"
assert functions["checked_dict_payload"]["payload"] == "i64"
PY

# Native error instances inherit the boundary metadata defaults too; callers should be able to
# inspect `.parameter`/`.expected` without special-casing whether the error came from conversion
# or from the Elisa function body.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/errors.c" \
    "$ROOT/test/repro/pymodule_errors.elisa" >/dev/null
grep -Fq 'PyObject_SetAttrString(elisa_error_type, "parameter", Py_None)' "$WORK/errors.c"
grep -Fq 'PyObject_SetAttrString(elisa_error_type, "expected", Py_None)' "$WORK/errors.c"

# A scalar error payload can still fail after a borrowed darray& input has created the wrapper
# arena. The generated failure path must release that arena before propagating Python errors.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/payload_errors.c" \
    "$ROOT/test/repro/pymodule_error_payload.elisa" >/dev/null
python3 - "$WORK/payload_errors.c" <<'PY'
import sys

source = open(sys.argv[1], encoding="utf-8").read()
start = source.index("static PyObject *elisa_py_fail_ref")
end = source.index("static const char *elisa_pymodule_struct_names", start)
wrapper = source[start:end]
assert "goto elisa_pymodule_error_payload_after_cleanup_failed;" in wrapper
assert "elisa_pymodule_error_payload_after_cleanup_failed:" in wrapper
assert "elisa_pymodule_error_payload_after_cleanup_done:" in wrapper
assert "arena_free(&arena);\n        return NULL;" in wrapper
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/errors.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_errors.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import errors

assert errors.__doc__ == "Elisa Python module errors."
assert errors.divide.__doc__ == "Elisa export of checked_divide."
assert errors.__all__ == ["divide", "flag", "float", "unsigned", "text", "rejected_text", "object", "checked_dict", "checked_view", "checked_list", "checked_list_result", "checked_list_payload", "checked_bytes_result", "checked_dict_list", "checked_dict_result", "checked_dict_payload", "ping", "DivideError", "ListError", "ListPayloadError", "DictResultError", "DictResultPayloadError", "ElisaError"]
assert str(inspect.signature(errors.divide)) == "(value, divisor)"
assert str(inspect.signature(errors.ping)) == "()"
assert errors.divide(value=10, divisor=2) == 5
assert errors.divide(10, 2) == 5
for bad_args, expected_parameter in ((("wrong", 2), "value"), ((1, "wrong"), "divisor")):
    try:
        errors.divide(*bad_args)
    except TypeError as exc:
        assert f"Elisa function 'divide' argument '{expected_parameter}':" in str(exc)
        assert exc.function == "divide"
        assert exc.parameter == expected_parameter
        assert exc.expected == "int"
    else:
        raise AssertionError("invalid scalar arguments should raise TypeError")

try:
    errors.divide(1, divisor="wrong")
except TypeError as exc:
    assert "Elisa function 'divide' argument 'divisor':" in str(exc)
    assert exc.function == "divide"
    assert exc.parameter == "divisor"
    assert exc.expected == "int"
else:
    raise AssertionError("invalid keyword scalar argument should raise TypeError")

try:
    errors.divide(divisor="wrong")
except TypeError as exc:
    assert "missing required argument 'value'" in str(exc)
    assert exc.function == "divide"
    assert exc.parameter == "value"
    assert exc.expected is None
else:
    raise AssertionError("missing earlier scalar argument should raise TypeError")

try:
    errors.divide(1)
except TypeError as exc:
    assert "Elisa function 'divide' argument error:" in str(exc)
    assert "missing required argument 'divisor'" in str(exc)
    assert exc.function == "divide"
    assert exc.parameter == "divisor"
    assert exc.expected is None
else:
    raise AssertionError("missing required arguments should raise TypeError")
assert errors.flag(True) is True
assert errors.float(1.25) == 1.25
try:
    errors.float("wrong")
except TypeError as exc:
    assert exc.function == "float"
    assert exc.parameter == "value"
    assert exc.expected == "float"
else:
    raise AssertionError("invalid float scalar should raise TypeError")
assert errors.unsigned(2**63 + 3) == 2**63 + 3
assert errors.text("ok") == "ok"
assert errors.text("") == ""
value = {"kept": True}
assert errors.object(value) is value
assert errors.ping() is None
assert errors.checked_dict({1: 2, 3: 4}) == 2
try:
    errors.checked_dict({})
except errors.ElisaError as exc:
    assert isinstance(exc, errors.DivideError)
    assert exc.function == "checked_dict"
else:
    raise AssertionError("dictionary error target should raise ElisaError")
assert errors.checked_view([4, 5]) == [4, 5]
try:
    errors.checked_view([])
except errors.ElisaError as exc:
    assert exc.function == "checked_view"
else:
    raise AssertionError("view-return error target should raise ElisaError")
assert errors.checked_list([7, 8]) == 7
try:
    errors.checked_list([])
except errors.ElisaError as exc:
    assert exc.function == "checked_list"
else:
    raise AssertionError("darray-parameter error target should raise ElisaError")
assert errors.checked_list_result([4, 5]) == [4, 5]
try:
    errors.checked_list_result([])
except errors.ElisaError as exc:
    assert isinstance(exc, errors.ListError)
    assert exc.function == "checked_list_result"
    assert exc.payload is None
else:
    raise AssertionError("darray-return error target should raise ElisaError")
assert errors.checked_list_payload([9]) == [9]
try:
    errors.checked_list_payload([])
except errors.ElisaError as exc:
    assert isinstance(exc, errors.ListPayloadError)
    assert exc.function == "checked_list_payload"
    assert exc.payload == 0
else:
    raise AssertionError("darray-return payload error target should raise ElisaError")
assert errors.checked_bytes_result(b"abc") == b"abc"
try:
    errors.checked_bytes_result(b"")
except errors.ElisaError as exc:
    assert exc.function == "checked_bytes_result"
else:
    raise AssertionError("bytes-return error target should raise ElisaError")
assert errors.checked_dict_list({1: 2}, [4, 5]) == [4, 5]
try:
    errors.checked_dict_list({}, [4, 5])
except errors.ElisaError as exc:
    assert exc.function == "checked_dict_list"
else:
    raise AssertionError("dictionary plus darray error target should raise ElisaError")
assert errors.checked_dict_result({1: 2, 3: 4}) == {1: 2, 3: 4}
try:
    errors.checked_dict_result({})
except errors.ElisaError as exc:
    assert isinstance(exc, errors.DictResultError)
    assert exc.function == "checked_dict_result"
else:
    raise AssertionError("dictionary-return error target should raise ElisaError")
assert errors.checked_dict_payload({1: 2}) == {1: 2}
try:
    errors.checked_dict_payload({})
except errors.ElisaError as exc:
    assert isinstance(exc, errors.DictResultPayloadError)
    assert exc.function == "checked_dict_payload"
    assert exc.payload == 0
else:
    raise AssertionError("dictionary-return payload error target should raise ElisaError")
try:
    errors.rejected_text("nope")
except errors.ElisaError as exc:
    assert isinstance(exc, RuntimeError)
    assert exc.code == 1
    assert exc.function == "rejected_text"
    assert "error code 1" in str(exc)
else:
    raise AssertionError("sview error should raise RuntimeError")
try:
    # Native errors must stamp per-instance metadata rather than inheriting mutable
    # class attributes from a previous caller.
    errors.ElisaError.payload = "stale payload"
    errors.ElisaError.parameter = "stale parameter"
    errors.ElisaError.expected = "stale expected"
    errors.DivideError.payload = "stale family payload"
    errors.DivideError.parameter = "stale family parameter"
    errors.DivideError.expected = "stale family expected"
    errors.divide(10, 0)
except errors.ElisaError as exc:
    assert isinstance(exc, errors.DivideError)
    assert exc.code == 1
    assert exc.function == "divide"
    assert exc.parameter is None
    assert exc.expected is None
    assert exc.payload is None
    assert "error code 1" in str(exc)
else:
    raise AssertionError("error-returning Elisa function should raise RuntimeError")
try:
    errors.flag(False)
except errors.ElisaError as exc:
    assert exc.code == 1
    assert exc.function == "flag"
    assert "error code 1" in str(exc)
else:
    raise AssertionError("bool error should raise RuntimeError")
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/payload_errors.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import payload_errors
import sys

assert payload_errors.maybe(4) == 4
for fn, value in ((payload_errors.fail, 7), (payload_errors.maybe, -9)):
    try:
        fn(value)
    except payload_errors.ElisaError as exc:
        assert exc.code == 1
        assert exc.function == fn.__name__
        assert exc.payload == value
        assert f"payload: {value!r}" in str(exc)
    else:
        raise AssertionError("payload error should raise ElisaError")
for fn, value in ((payload_errors.fail_bool, True), (payload_errors.fail_float, 1.25)):
    try:
        fn(value)
    except payload_errors.ElisaError as exc:
        assert exc.payload == value
    else:
        raise AssertionError("numeric payload error should raise ElisaError")
try:
    payload_errors.fail_dict({1: 2, 3: 4})
except payload_errors.ElisaError as exc:
    assert exc.function == "fail_dict"
    assert exc.payload == 2
else:
    raise AssertionError("dictionary payload error should raise ElisaError")
try:
    payload_errors.fail_ref([1, 2, 3])
except payload_errors.ElisaError as exc:
    assert exc.function == "fail_ref"
    assert exc.payload == 3
else:
    raise AssertionError("darray-ref scalar payload error should raise ElisaError")
values = [1, 2, 3]
values_refcount = sys.getrefcount(values)
for _ in range(100):
    try:
        payload_errors.fail_ref(values)
    except payload_errors.ElisaError:
        pass
assert sys.getrefcount(values) == values_refcount
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/payload_text.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_text.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import payload_text

for fn, value, expected in ((payload_text.fail_sview, "héllo", "héllo"), (payload_text.fail_cstr, "world", "world")):
    try:
        fn(value)
    except payload_text.ElisaError as exc:
        assert exc.payload == expected
    else:
        raise AssertionError("text payload should raise ElisaError")
obj = {"kept": True}
try:
    payload_text.fail_object(obj)
except payload_text.ElisaError as exc:
    assert exc.payload is obj
else:
    raise AssertionError("object payload should raise ElisaError")
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/payload_multi.json" \
    "$ROOT/test/repro/pymodule_error_payload_multi.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/payload_multi.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail"]["raises"] == "MultiPayloadError"
assert functions["fail"]["payload"] == "struct"
assert functions["fail_other"]["payload"] == "struct"
variants = {variant["name"]: variant for variant in functions["fail"]["payload_variants"]}
assert variants["Bad"]["fields"] == [
    {"name": "code", "type": "i64"},
    {"name": "detail", "type": "sview"},
]
assert variants["Other"]["fields"] == [
    {"name": "label", "type": "cstr"},
    {"name": "value", "type": "py::Object"},
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/payload_multi.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_multi.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import payload_multi

assert payload_multi.MultiPayloadErrorBadPayload.__module__ == "payload_multi"
assert payload_multi.MultiPayloadErrorOtherPayload.__module__ == "payload_multi"
assert payload_multi.MultiPayloadErrorPayload.__args__ == (
    payload_multi.MultiPayloadErrorBadPayload,
    payload_multi.MultiPayloadErrorOtherPayload,
)
try:
    payload_multi.fail(7, "a\x00b")
except payload_multi.ElisaError as exc:
    assert exc.code == 1
    assert exc.function == "fail"
    assert exc.payload == {"variant": "Bad", "code": 7, "detail": "a\x00b"}
else:
    raise AssertionError("multi-field payload should raise ElisaError")

obj = {"kept": True}
try:
    payload_multi.fail_other("oops", obj)
except payload_multi.ElisaError as exc:
    assert exc.payload["variant"] == "Other"
    assert exc.payload["label"] == "oops"
    assert exc.payload["value"] is obj
else:
    raise AssertionError("second structured payload variant should raise ElisaError")
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/payload_darray.json" \
    "$ROOT/test/repro/pymodule_error_payload_darray.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/payload_darray.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail_list"]["payload"] == "darray[i64]"
assert functions["fail_bytes"]["payload"] == "darray[u8]"
assert functions["fail_structured"]["payload"] == "struct"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_darray.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_darray.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_darray

for fn, value in ((error_payload_darray.fail_list, [4, 5, 6]), (error_payload_darray.fail_bytes, b"a\x00b")):
    try:
        fn(value)
    except error_payload_darray.ElisaError as exc:
        assert exc.function == fn.__name__
        assert exc.payload == value
    else:
        raise AssertionError("aggregate payload should raise ElisaError")

try:
    error_payload_darray.fail_constructed()
except error_payload_darray.ElisaError as exc:
    assert exc.payload == [9, 10]
else:
    raise AssertionError("constructed aggregate payload should raise ElisaError")

try:
    error_payload_darray.fail_structured([7, 8], "a\x00b")
except error_payload_darray.ElisaError as exc:
    assert exc.payload == {"variant": "Empty", "items": [7, 8], "label": "a\x00b"}
else:
    raise AssertionError("structured aggregate payload should raise ElisaError")
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/payload_view.json" \
    "$ROOT/test/repro/pymodule_error_payload_view.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/payload_view.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail_view"]["payload"] == "view[i64]"
assert functions["fail_bytes"]["payload"] == "view[u8]"
assert functions["fail_structured"]["payload"] == "struct"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_view.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_view.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_view

for fn, value in ((error_payload_view.fail_view, [4, 5, 6]), (error_payload_view.fail_bytes, b"a\x00b")):
    try:
        fn(value)
    except error_payload_view.ElisaError as exc:
        assert exc.function == fn.__name__
        assert exc.payload == value
    else:
        raise AssertionError("view payload should raise ElisaError")

try:
    error_payload_view.fail_structured([7, 8], "a\x00b")
except error_payload_view.ElisaError as exc:
    assert exc.payload == {"variant": "Empty", "items": [7, 8], "label": "a\x00b"}
else:
    raise AssertionError("structured view payload should raise ElisaError")
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/container_errors.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_darray.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import container_errors

assert container_errors.count() == {}
PY

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/unsupported_target.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_unsupported_target.elisa" >"$WORK/unsupported.log" 2>&1; then
    echo "unsupported native pymodule target should be rejected before linking" >&2
    exit 1
fi
grep -Fq "native pymodule symbol missing from object" "$WORK/unsupported.log"

echo "pymodule errors smoke OK"
