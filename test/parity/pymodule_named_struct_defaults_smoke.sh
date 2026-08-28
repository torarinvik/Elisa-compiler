#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule named-record defaults smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_named_struct_defaults.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/named_struct_defaults.json" "$SOURCE" >/dev/null
python3 - "$WORK/named_struct_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["module"] == "named_struct_defaults"
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["list_default"]["parameters"] == [{
    "name": "points",
    "type": "darray[Point]",
    "default": '[{"x": 1, "y": 2}, {"x": 3, "y": 4}]',
}]
assert functions["map_default"]["parameters"] == [{
    "name": "points",
    "type": "dict[i64,Point]",
    "default": '{1: {"x": 5, "y": 6}}',
}]
assert functions["map_list_default"]["parameters"] == [{
    "name": "points",
    "type": "dict[i64,darray[Point]]",
    "default": '{1: [{"x": 11, "y": 12}]}',
}]
assert functions["nested_default"]["parameters"] == [{
    "name": "points",
    "type": "darray[darray[Point]]",
    "default": '[[{"x": 7, "y": 8}], [{"x": 9, "y": 10}]]',
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/named_struct_defaults.pyi" "$SOURCE" >/dev/null
grep -Fq 'def list_default(points: Sequence[Point | PointInput] = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]) -> list[Point]: ...' "$WORK/named_struct_defaults.pyi"
grep -Fq 'def map_default(points: Mapping[int, Point | PointInput] = {1: {"x": 5, "y": 6}}) -> dict[int, Point]: ...' "$WORK/named_struct_defaults.pyi"
grep -Fq 'def map_list_default(points: Mapping[int, Sequence[Point | PointInput]] = {1: [{"x": 11, "y": 12}]}) -> dict[int, list[Point]]: ...' "$WORK/named_struct_defaults.pyi"
grep -Fq 'def nested_default(points: Sequence[Sequence[Point | PointInput]] = [[{"x": 7, "y": 8}], [{"x": 9, "y": 10}]]) -> list[list[Point]]: ...' "$WORK/named_struct_defaults.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/named_struct_defaults.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/named_struct_defaults.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import named_struct_defaults as module

assert module.list_default() == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
assert module.map_default() == {1: {"x": 5, "y": 6}}
assert module.map_list_default() == {1: [{"x": 11, "y": 12}]}
assert module.nested_default() == [[{"x": 7, "y": 8}], [{"x": 9, "y": 10}]]

# Every omitted call gets a fresh recursive value, including named-record dictionaries.
first = module.list_default()
first[0]["x"] = 100
assert module.list_default()[0]["x"] == 1

first_map = module.map_default()
first_map[1]["y"] = 200
assert module.map_default()[1]["y"] == 6

first_map_list = module.map_list_default()
first_map_list[1][0]["x"] = 300
assert module.map_list_default()[1][0]["x"] == 11

first_nested = module.nested_default()
first_nested[0][0]["y"] = 400
assert module.nested_default()[0][0]["y"] == 8

assert module.list_default([{"x": -1, "y": 2}]) == [{"x": -1, "y": 2}]
assert module.map_default({9: {"x": 3, "y": 4}}) == {9: {"x": 3, "y": 4}}
print("pymodule named-record defaults smoke OK")
PY
