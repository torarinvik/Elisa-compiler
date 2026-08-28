#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nested named-dict values smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_nested_dict_struct_values.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["roundtrip"]["parameters"][0]["type"] == "dict[i64,dict[cstr,Point]]"
assert functions["roundtrip"]["return"] == "dict[i64,dict[cstr,Point]]"
assert functions["roundtrip_rows"]["parameters"][0]["type"] == "darray[dict[i64,dict[cstr,Point]]]"
assert functions["roundtrip_rows"]["return"] == "darray[dict[i64,dict[cstr,Point]]]"
assert manifest["structs"][1]["fields"] == [{"name": "values", "type": "dict[i64,dict[cstr,Point]]"}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/nested_dict_struct_values.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Mapping[int, Mapping[str | bytes, Point | PointInput]]) -> dict[int, dict[str, Point]]: ...' "$WORK/nested_dict_struct_values.pyi"
grep -Fq 'def roundtrip_rows(values: Sequence[Mapping[int, Mapping[str | bytes, Point | PointInput]]]) -> list[dict[int, dict[str, Point]]]: ...' "$WORK/nested_dict_struct_values.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/nested_dict_struct_values.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nested_dict_struct_values.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nested_dict_struct_values as module

point = {"x": 7, "label": "α\x00β"}
value = {1: {"first": point}, 2: {}}
assert module.roundtrip(value) == value
assert module.roundtrip_catalog({"values": value}) == {"values": value}
rows = [{1: {"first": point}}, {}, {2: {"last": {"x": -3, "label": "done"}}}]
assert module.roundtrip_rows(rows) == rows

for function, bad in (
    (module.roundtrip, {1: {"first": {"x": "bad", "label": "ok"}}}),
    (module.roundtrip_rows, [{1: []}]),
):
    try:
        function(bad)
    except (TypeError, KeyError):
        pass
    else:
        raise AssertionError((function.__name__, bad))

print("pymodule nested named-dict values smoke OK")
PY
