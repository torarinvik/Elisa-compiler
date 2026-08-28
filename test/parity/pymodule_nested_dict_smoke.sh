#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nested-dict smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" \
    "$ROOT/test/repro/pymodule_nested_dict_probe.elisa" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert manifest["structs"] == [{
    "name": "NestedPayload",
    "fields": [{"name": "values", "type": "dict[i64,dict[cstr,i64]]"}],
}]
assert functions["roundtrip"]["parameters"][0]["type"] == "dict[i64,dict[i64,i64]]"
assert functions["roundtrip"]["return"] == "dict[i64,dict[i64,i64]]"
assert functions["roundtrip_lists"]["return"] == "dict[i64,dict[cstr,darray[i64]]]"
assert functions["roundtrip_optional"]["return"] == "dict[i64,dict[cstr,i64?]]"
PY

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/nested_dict_probe.pyi" "$ROOT/test/repro/pymodule_nested_dict_probe.elisa" >/dev/null
grep -Fq 'def roundtrip(values: Mapping[int, Mapping[int, int]]) -> dict[int, dict[int, int]]: ...' "$WORK/nested_dict_probe.pyi"
grep -Fq 'def roundtrip_lists(values: Mapping[int, Mapping[str | bytes, Sequence[int]]]) -> dict[int, dict[str, list[int]]]: ...' "$WORK/nested_dict_probe.pyi"
grep -Fq 'values: Mapping[int, Mapping[str | bytes, int]]' "$WORK/nested_dict_probe.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/nested_dict_probe.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nested_dict_probe.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_nested_dict_probe.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nested_dict_probe

value = {1: {10: 20, 11: -2}, 2: {}}
assert nested_dict_probe.roundtrip(value) == value
assert nested_dict_probe.roundtrip_struct({"values": {1: {"a": 2, "b": -3}, 2: {}}}) == {"values": {1: {"a": 2, "b": -3}, 2: {}}}
assert nested_dict_probe.roundtrip_text({"a": {1: "one", 2: "α"}, "empty": {}}) == {"a": {1: "one", 2: "α"}, "empty": {}}
assert nested_dict_probe.roundtrip_lists({1: {"a": [1, 2], "b": []}, 2: {"x": [-3]}}) == {1: {"a": [1, 2], "b": []}, 2: {"x": [-3]}}
assert nested_dict_probe.roundtrip_optional({1: {"a": 2, "none": None}}) == {1: {"a": 2, "none": None}}
payload = {"x": [1]}
returned = nested_dict_probe.roundtrip_objects({1: {"payload": payload, "none": None}})
assert returned[1]["payload"] is payload
assert returned[1]["none"] is None

for function, bad in (
    (nested_dict_probe.roundtrip, {1: [2]}),
    (nested_dict_probe.roundtrip, {1: {"x": 2}}),
    (nested_dict_probe.roundtrip_lists, {1: {"x": [2**70]}}),
    (nested_dict_probe.roundtrip_optional, {1: {"x": "bad"}}),
):
    try:
        function(bad)
    except (TypeError, OverflowError):
        pass
    else:
        raise AssertionError((function.__name__, bad))

print("pymodule nested dictionary smoke OK")
PY
