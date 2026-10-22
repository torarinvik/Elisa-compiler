#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
SOURCE="$ROOT/test/repro/pymodule_dict_set_probe.elisa"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict-set smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["roundtrip"]["parameters"] == [{"name": "values", "type": "dict[i64,set[i64]]"}]
assert functions["roundtrip"]["return"] == "dict[i64,set[i64]]"
assert functions["roundtrip_text"]["parameters"] == [{"name": "values", "type": "dict[cstr,set[sview]]"}]
assert functions["roundtrip_text"]["return"] == "dict[cstr,set[sview]]"
assert functions["roundtrip_nested"]["parameters"] == [{"name": "values", "type": "dict[i64,dict[i64,set[i64]]]"}]
assert functions["roundtrip_nested"]["return"] == "dict[i64,dict[i64,set[i64]]]"
assert functions["count_bool"]["parameters"] == [{"name": "values", "type": "set[bool]"}]
assert functions["roundtrip_bool"]["return"] == "set[bool]"
assert functions["contains_bool"]["parameters"] == [
    {"name": "values", "type": "set[bool]"},
    {"name": "key", "type": "bool"},
]
assert functions["contains_bool"]["return"] == "bool"
assert functions["contains_i64"]["parameters"] == [
    {"name": "values", "type": "set[i64]"},
    {"name": "key", "type": "i64"},
]
assert functions["contains_i64"]["return"] == "bool"
assert functions["count_i64"]["parameters"] == [
    {"name": "values", "type": "set[i64]"},
]
assert functions["count_i64"]["return"] == "usize"
assert functions["contains_i8"]["parameters"] == [
    {"name": "values", "type": "set[i8]"},
    {"name": "key", "type": "i8"},
]
assert functions["contains_i8"]["return"] == "bool"
assert functions["contains_u8"]["parameters"] == [
    {"name": "values", "type": "set[u8]"},
    {"name": "key", "type": "u8"},
]
assert functions["contains_u8"]["return"] == "bool"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/dict_set_probe.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Mapping[int, Iterable[int]]) -> dict[int, set[int]]: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def roundtrip_text(values: Mapping[str | bytes, Iterable[str | bytes]]) -> dict[str, set[str]]: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def roundtrip_nested(values: Mapping[int, Mapping[int, Iterable[int]]]) -> dict[int, dict[int, set[int]]]: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def roundtrip_bool(values: Iterable[bool]) -> set[bool]: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def contains_bool(values: Iterable[bool], key: bool) -> bool: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def contains_i64(values: Iterable[int], key: int) -> bool: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def count_i64(values: Iterable[int]) -> int: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def contains_i8(values: Iterable[int], key: int) -> bool: ...' "$WORK/dict_set_probe.pyi"
grep -Fq 'def contains_u8(values: Iterable[int], key: int) -> bool: ...' "$WORK/dict_set_probe.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dict_set_probe.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_set_probe.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_set_probe

value = {1: {2, 3}, 4: set()}
assert dict_set_probe.roundtrip(value) == value
assert dict_set_probe.roundtrip({1: [2, 3], 4: ()}) == value
text_value = {"α": {"one", "two"}, "empty": set()}
assert dict_set_probe.roundtrip_text(text_value) == text_value
assert dict_set_probe.roundtrip_text({"α": ["one", "two"]}) == {"α": {"one", "two"}}
assert dict_set_probe.roundtrip_text({"same": ["x", "x"]}) == {"same": {"x"}}
assert dict_set_probe.roundtrip_text({"same": ["first"], b"same": ["last"]}) == {"same": {"last"}}
nested_value = {1: {10: {20, 30}, 11: set()}, 2: {}}
assert dict_set_probe.roundtrip_nested(nested_value) == nested_value
assert dict_set_probe.count_bool({2, 3}) == 1
assert dict_set_probe.count_bool([2, 3]) == 1
assert dict_set_probe.count_bool([0, False, 2, 3]) == 2
assert dict_set_probe.roundtrip_bool([2, 3]) == {True}
assert dict_set_probe.contains_bool([2, 3], True)
assert not dict_set_probe.contains_bool([2, 3], False)
assert dict_set_probe.contains_i64([1, 4], 1)
assert dict_set_probe.contains_i64([-1, 4], -1)
assert dict_set_probe.count_i64([1, True]) == 1
assert dict_set_probe.count_i64([True, 1]) == 1
assert dict_set_probe.contains_i8([-1, 4], -1)
assert dict_set_probe.contains_u8([255, 4], 255)
for bad in ([1.0, 1], [1, 1.0]):
    try:
        dict_set_probe.contains_i64(bad, 1)
    except TypeError:
        pass
    else:
        raise AssertionError(("contains_i64 accepted a float set element", bad))

for function, bad in (
    (dict_set_probe.roundtrip, {"bad": {1}}),
    (dict_set_probe.roundtrip, {1: {2**70}}),
    (dict_set_probe.roundtrip_text, {"bad": {1}}),
    (dict_set_probe.roundtrip_text, {"bad\x00": {"ok"}}),
):
    try:
        function(bad)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError((function.__name__, bad))

try:
    dict_set_probe.roundtrip_text({"bad": {1}})
except TypeError as exc:
    assert "at path ['bad'][1]:" in str(exc)
    assert exc.function == "roundtrip_text"
    assert exc.parameter == "values"
    assert exc.path == "['bad'][1]"
else:
    raise AssertionError("nested set element error did not include mapping and value paths")

print("pymodule dictionary-of-sets smoke OK")
PY
