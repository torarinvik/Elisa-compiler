#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nested named aggregate smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_nested_dict_named_aggregates.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["roundtrip_lists"]["parameters"][0]["type"] == "dict[i64,dict[cstr,darray[Point]]]"
assert functions["roundtrip_lists"]["return"] == "dict[i64,dict[cstr,darray[Point]]]"
assert functions["roundtrip_views"]["parameters"][0]["type"] == "dict[i64,dict[cstr,view[Point]]]"
assert functions["roundtrip_views"]["return"] == "dict[i64,dict[cstr,view[Point]]]"
assert functions["roundtrip_list_rows"]["parameters"][0]["type"] == "darray[dict[i64,dict[cstr,darray[Point]]]]"
assert functions["roundtrip_list_rows"]["return"] == "darray[dict[i64,dict[cstr,darray[Point]]]]"
assert functions["roundtrip_view_rows"]["parameters"][0]["type"] == "darray[dict[i64,dict[cstr,view[Point]]]]"
assert functions["roundtrip_view_rows"]["return"] == "darray[dict[i64,dict[cstr,view[Point]]]]"
assert functions["roundtrip_catalog"]["parameters"][0]["type"] == "Catalog"
assert functions["roundtrip_catalog"]["return"] == "Catalog"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/nested_dict_named_aggregates.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip_lists(values: Mapping[int, Mapping[str | bytes, Sequence[Point | PointInput]]]) -> dict[int, dict[str, list[Point]]]: ...' "$WORK/nested_dict_named_aggregates.pyi"
grep -Fq 'def roundtrip_views(values: Mapping[int, Mapping[str | bytes, Sequence[Point | PointInput]]]) -> dict[int, dict[str, list[Point]]]: ...' "$WORK/nested_dict_named_aggregates.pyi"
grep -Fq 'def roundtrip_list_rows(values: Sequence[Mapping[int, Mapping[str | bytes, Sequence[Point | PointInput]]]]) -> list[dict[int, dict[str, list[Point]]]]: ...' "$WORK/nested_dict_named_aggregates.pyi"
grep -Fq 'def roundtrip_view_rows(values: Sequence[Mapping[int, Mapping[str | bytes, Sequence[Point | PointInput]]]]) -> list[dict[int, dict[str, list[Point]]]]: ...' "$WORK/nested_dict_named_aggregates.pyi"
grep -Fq 'class Catalog(TypedDict):' "$WORK/nested_dict_named_aggregates.pyi"
grep -Fq '    rows: dict[int, dict[str, list[Point]]]' "$WORK/nested_dict_named_aggregates.pyi"
grep -Fq '    views: dict[int, dict[str, list[Point]]]' "$WORK/nested_dict_named_aggregates.pyi"
grep -Fq 'def roundtrip_catalog(catalog: Catalog | CatalogInput) -> Catalog: ...' "$WORK/nested_dict_named_aggregates.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/nested_dict_named_aggregates.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nested_dict_named_aggregates.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nested_dict_named_aggregates as module

value = {1: {"a": [{"x": 2, "label": "α\x00β"}, {"x": -1, "label": "done"}], "empty": []}, 2: {}}
assert module.roundtrip_lists(value) == value
assert module.roundtrip_views(value) == value
rows = [value, {}, {3: {"row": [{"x": 8, "label": "row"}]}}]
assert module.roundtrip_list_rows(rows) == rows
assert module.roundtrip_view_rows(rows) == rows
assert module.roundtrip_catalog({"rows": value, "views": value}) == {"rows": value, "views": value}

for function, bad in (
    (module.roundtrip_lists, {1: {"a": [{"x": "bad", "label": "ok"}]}}),
    (module.roundtrip_views, {1: {"a": [{"x": 1}]}}),
    (module.roundtrip_list_rows, [{1: {"a": [{"x": 1}]}}]),
):
    try:
        function(bad)
    except (TypeError, KeyError):
        pass
    else:
        raise AssertionError((function.__name__, bad))

print("pymodule nested named aggregate smoke OK")
PY
