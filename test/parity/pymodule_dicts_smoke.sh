#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dicts smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dicts.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_dicts.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
from collections import UserDict
import dicts

assert dicts.count_i64({}) == 0
assert dicts.count_i64({1: 2, 3: 4}) == 2
try:
    dicts.count_i64([1, 2])
except TypeError as exc:
    assert "Elisa function 'count_i64' argument 'values':" in str(exc)
    assert exc.function == "count_i64"
    assert exc.parameter == "values"
    assert exc.expected == "mapping"
else:
    raise AssertionError("non-mapping dictionary input should fail with parameter context")
assert dicts.count_i64(values={1: 2}) == 1
assert dicts.count_i64(UserDict({1: 2, 3: 4})) == 2
assert dicts.count_after_key(99, {1: 2, 3: 4}) == 2
assert dicts.count_text({"a": 1, "b": 2}) == 2
assert dicts.count_u64({1: 2, 3: 4}) == 2
assert dicts.count_float({1: 1.5, 2: 2.5}) == 2
assert dicts.count_bool({"yes": True, "no": False}) == 2
assert dicts.count_bool_keys({True: 1, False: 0}) == 2
assert dicts.get_i64({1: 40, 2: 2}, 1) == 40
assert dicts.get_i64({1: 40, 2: 2}, key=2) == 2
assert dicts.get_i64({1: 40}, 99) == -1
assert dicts.pair_count({1: 2}, {"ok": True, "no": False}) == 3
assert dicts.empty_i64() == {}
assert dicts.roundtrip_i64({}) == {}
assert dicts.roundtrip_i64({1: 40, 2: 2}) == {1: 40, 2: 2}
assert dicts.roundtrip_i32({1: -2147483648, 2: 2147483647}) == {1: -2147483648, 2: 2147483647}
assert dicts.roundtrip_u8({"low": 0, "high": 255}) == {"low": 0, "high": 255}
assert dicts.roundtrip_text({"yes": True, "no": False}) == {"yes": True, "no": False}
assert dicts.roundtrip_float({1: 1.5, 2: 2.5}) == {1: 1.5, 2: 2.5}
f32_values = dicts.roundtrip_f32({1: 1.5, 2: -2.25})
assert abs(f32_values[1] - 1.5) < 1e-6
assert abs(f32_values[2] + 2.25) < 1e-6
assert dicts.roundtrip_u64({1: 2, 2**63: 2**64 - 1}) == {1: 2, 2**63: 2**64 - 1}
assert dicts.roundtrip_bool_keys({True: 11, False: 22}) == {True: 11, False: 22}
assert dicts.roundtrip_i8_keys({-128: 1, 127: 2}) == {-128: 1, 127: 2}
assert dicts.get_i8({-128: 10, -1: 20, 127: 30}, -1) == 20
assert dicts.roundtrip_i16_keys({-32768: 1, 32767: 2}) == {-32768: 1, 32767: 2}
assert dicts.roundtrip_i32_keys({-(2**31): 1, 2**31 - 1: 2}) == {-(2**31): 1, 2**31 - 1: 2}
assert dicts.roundtrip_int_keys({-(2**63) + 1: 1, 2**63 - 1: 2}) == {-(2**63) + 1: 1, 2**63 - 1: 2}
assert dicts.roundtrip_isize_keys({-(2**63) + 1: 1, 2**63 - 1: 2}) == {-(2**63) + 1: 1, 2**63 - 1: 2}
assert dicts.roundtrip_char_keys({0: 1, 0x10FFFF: 2}) == {0: 1, 0x10FFFF: 2}
assert dicts.roundtrip_u8_keys({0: 1, 255: 2}) == {0: 1, 255: 2}
assert dicts.get_u8({0: 10, 255: 20}, 255) == 20
assert dicts.roundtrip_u16_keys({0: 1, 65535: 2}) == {0: 1, 65535: 2}
assert dicts.roundtrip_u32_keys({0: 1, 2**32 - 1: 2}) == {0: 1, 2**32 - 1: 2}
assert dicts.roundtrip_usize_keys({0: 1, 2**63: 2}) == {0: 1, 2**63: 2}
assert dicts.roundtrip_uintptr_keys({0: 1, 2**63: 2}) == {0: 1, 2**63: 2}
obj = {"kind": "payload"}
assert dicts.count_objects({1: obj, 2: None}) == 2
returned = dicts.roundtrip_objects({"payload": obj, "empty": None})
assert returned["payload"] is obj
assert returned["empty"] is None
text_values = {"one": "α", "empty": ""}
assert dicts.roundtrip_cstr_values(text_values) == text_values
assert dicts.roundtrip_cstr_values({b"one": b"\xce\xb1", b"empty": b""}) == text_values
assert dicts.roundtrip_sview_values({1: "α", 2: ""}) == {1: "α", 2: ""}

nested_values = {1: [2, 3], 2: []}
assert dicts.nested_count(nested_values) == 2
assert dicts.roundtrip_nested(nested_values) == nested_values
assert dicts.roundtrip_nested({1: (2, 3)}) == {1: [2, 3]}
assert dicts.roundtrip_nested({1: (item for item in (7, 8))}) == {1: [7, 8]}
assert dicts.roundtrip_nested_optional_scalars({1: [2, None, -4], 2: []}) == {1: [2, None, -4], 2: []}
try:
    dicts.roundtrip_nested_optional_scalars({1: ["bad"]})
except TypeError:
    pass
else:
    raise AssertionError("invalid nested optional scalar dictionary value accepted")
assert dicts.roundtrip_nested_optional_float({"values": [1.5, None, -2.25]}) == {"values": [1.5, None, -2.25]}
try:
    dicts.roundtrip_nested_optional_float({"bad": [object()]})
except TypeError:
    pass
else:
    raise AssertionError("invalid nested optional float dictionary value accepted")
assert dicts.roundtrip_nested_bytes({"raw": b"\x00\x01\xff", "empty": b""}) == {
    "raw": b"\x00\x01\xff", "empty": b""
}
assert dicts.roundtrip_nested_bytes({"array": bytearray(b"abc"), "view": memoryview(b"xyz")}) == {
    "array": b"abc", "view": b"xyz"
}
try:
    dicts.roundtrip_nested_bytes({"bad": [256]})
except (TypeError, ValueError, OverflowError):
    pass
else:
    raise AssertionError("invalid nested byte dictionary value accepted")
obj = {"kind": "nested"}
nested_objects = dicts.roundtrip_nested_objects({1: [obj, None], 2: []})
assert nested_objects[1][0] is obj
assert nested_objects[1][1] is None
assert nested_objects[2] == []
try:
    dicts.roundtrip_nested_objects({1: 42})
except TypeError:
    pass
else:
    raise AssertionError("invalid nested object dictionary value accepted")
optional_obj = {"kind": "optional"}
optional_nested = dicts.roundtrip_nested_optional_objects({1: [optional_obj, None], 2: []})
assert optional_nested[1][0] is optional_obj
assert optional_nested[1][1] is None
assert optional_nested[2] == []
try:
    dicts.roundtrip_nested_optional_objects({1: 42})
except TypeError:
    pass
else:
    raise AssertionError("invalid nested optional-object dictionary value accepted")
for value in ({1: 7}, {1: ["bad"]}):
    try:
        dicts.roundtrip_nested(value)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid nested dictionary value accepted")
assert dicts.nested_float_count({1: [1.5, -2.25], 2: []}) == 2
assert dicts.roundtrip_nested_f64({1: [1.5, -2.25], 2: []}) == {1: [1.5, -2.25], 2: []}
assert dicts.roundtrip_nested_f64({1: (item for item in (3.5, 4.5))}) == {1: [3.5, 4.5]}
assert dicts.roundtrip_nested_f32({"one": [1.5, -2.25], "empty": []}) == {"one": [1.5, -2.25], "empty": []}
assert dicts.roundtrip_nested_i8({1: [-128, 0, 127], 2: []}) == {1: [-128, 0, 127], 2: []}
assert dicts.roundtrip_nested_i16({"one\x00key": [-32768, 32767]}) == {"one\x00key": [-32768, 32767]}
assert dicts.roundtrip_nested_i32({1: [-(2**31), 2**31 - 1]}) == {1: [-(2**31), 2**31 - 1]}
assert dicts.roundtrip_nested_int({1: [-(2**63) + 1, 2**63 - 1]}) == {1: [-(2**63) + 1, 2**63 - 1]}
assert dicts.roundtrip_nested_isize({1: [-(2**63) + 1, 2**63 - 1]}) == {1: [-(2**63) + 1, 2**63 - 1]}
assert dicts.roundtrip_nested_char({1: [0, 0x10FFFF]}) == {1: [0, 0x10FFFF]}
assert dicts.roundtrip_nested_u16({1: [0, 65535]}) == {1: [0, 65535]}
assert dicts.roundtrip_nested_u32({1: [0, 2**32 - 1]}) == {1: [0, 2**32 - 1]}
assert dicts.roundtrip_nested_u64({1: [0, 2**64 - 1]}) == {1: [0, 2**64 - 1]}
assert dicts.roundtrip_nested_usize({1: [0, 2**63]}) == {1: [0, 2**63]}
assert dicts.roundtrip_nested_uintptr({1: [0, 2**63]}) == {1: [0, 2**63]}
assert dicts.roundtrip_nested_bool({1: [True, False, 1, 0]}) == {1: [True, False, True, False]}
for fn, value in (
    (dicts.roundtrip_nested_i8, {1: [128]}),
    (dicts.roundtrip_nested_i16, {"bad": [-32769]}),
    (dicts.roundtrip_nested_u16, {1: [-1]}),
    (dicts.roundtrip_nested_u32, {1: [2**32]}),
    (dicts.roundtrip_nested_i32, {1: [object()]}),
):
    try:
        fn(value)
    except (TypeError, OverflowError):
        pass
    else:
        raise AssertionError("invalid nested scalar dictionary value accepted")
assert dicts.roundtrip_nested_cstr({"one": ["α", ""], "empty": []}) == {"one": ["α", ""], "empty": []}
assert dicts.roundtrip_nested_cstr({b"one": [b"\xce\xb1", b""], b"empty": []}) == {"one": ["α", ""], "empty": []}
assert dicts.roundtrip_nested_cstr({"one": (item for item in ("x", "y"))}) == {"one": ["x", "y"]}
assert dicts.roundtrip_nested_sview({1: ["α", "", "line\x00break"]}) == {1: ["α", "", "line\x00break"]}
assert dicts.roundtrip_nested_sview({1: [b"\xce\xb1", b"", b"line\x00break"]}) == {1: ["α", "", "line\x00break"]}
assert dicts.roundtrip_nested_optional_cstr({"one": ["α", None, ""], "empty": []}) == {
    "one": ["α", None, ""], "empty": []
}
assert dicts.roundtrip_nested_optional_cstr({"one": (item for item in (None, "x"))}) == {"one": [None, "x"]}
assert dicts.roundtrip_nested_optional_sview({1: ["α", None, "line\x00break"], 2: []}) == {
    1: ["α", None, "line\x00break"], 2: []
}
for fn, value in (
    (dicts.roundtrip_nested_optional_cstr, {"bad": [object()]}),
    (dicts.roundtrip_nested_optional_sview, {1: [object()]}),
):
    try:
        fn(value)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid nested optional text dictionary value accepted")
try:
    dicts.roundtrip_nested_optional_cstr({"bad": ["line\x00break"]})
except ValueError:
    pass
else:
    raise AssertionError("NUL-containing nested optional cstr accepted")
for fn, value in ((dicts.roundtrip_nested_f64, {1: ["bad"]}), (dicts.roundtrip_nested_f32, {"bad": [object()]})):
    try:
        fn(value)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid floating nested dictionary value accepted")
try:
    dicts.roundtrip_nested_cstr({"bad": ["line\x00break"]})
except ValueError:
    pass
else:
    raise AssertionError("NUL-containing nested cstr accepted")
try:
    dicts.roundtrip_nested_sview({1: [object()]})
except TypeError:
    pass
else:
    raise AssertionError("invalid nested sview value accepted")
for fn, value in ((dicts.roundtrip_cstr_values, {"bad": 1}), (dicts.roundtrip_sview_values, {1: 2})):
    try:
        fn(value)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid text dictionary value accepted")

for value in ({"bad\x00key": "ok"}, {"ok": "bad\x00value"}):
    try:
        dicts.roundtrip_cstr_values(value)
    except ValueError:
        pass
    else:
        raise AssertionError("NUL-containing cstr dictionary text accepted")

for fn, value in ((dicts.count_i64, []), (dicts.count_text, {1: 2}), (dicts.count_u64, {-1: 2})):
    try:
        fn(value)
    except (TypeError, OverflowError):
        pass
    else:
        raise AssertionError("invalid dictionary boundary accepted")

try:
    dicts.count_i64({1: 2**100})
except OverflowError:
    pass
else:
    raise AssertionError("dictionary value overflow should fail")
try:
    dicts.roundtrip_i64({1: "bad"})
except TypeError as exc:
    assert "at path [1]:" in str(exc)
    assert exc.function == "roundtrip_i64"
    assert exc.parameter == "values"
    assert exc.path == "[1]"
else:
    raise AssertionError("dictionary value conversion should identify its key")
try:
    dicts.roundtrip_i64({"bad": 1})
except TypeError as exc:
    assert "at path ['bad']:" in str(exc)
    assert exc.function == "roundtrip_i64"
    assert exc.parameter == "values"
    assert exc.path == "['bad']"
else:
    raise AssertionError("dictionary key conversion should identify its key")
try:
    dicts.roundtrip_nested({1: [2, "bad"]})
except TypeError as exc:
    assert "at path [1][1]:" in str(exc)
    assert exc.function == "roundtrip_nested"
    assert exc.parameter == "values"
    assert exc.path == "[1][1]"
else:
    raise AssertionError("nested dictionary conversion should identify key and index")
for fn, value in (
    (dicts.roundtrip_i32, {1: 2**31}),
    (dicts.roundtrip_i32, {1: -(2**31) - 1}),
    (dicts.roundtrip_u8, {"bad": 256}),
    (dicts.roundtrip_u8, {"bad": -1}),
    (dicts.roundtrip_i8_keys, {128: 1}),
    (dicts.roundtrip_i8_keys, {-129: 1}),
    (dicts.roundtrip_u8_keys, {256: 1}),
    (dicts.roundtrip_u8_keys, {-1: 1}),
):
    try:
        fn(value)
    except OverflowError:
        pass
    else:
        raise AssertionError("narrow dictionary value overflow should fail")
PY

echo "pymodule dicts smoke OK"
