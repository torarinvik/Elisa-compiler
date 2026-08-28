#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict-darray-named-struct smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_dict_darray_struct_values.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["roundtrip"]["parameters"][0]["type"] == "dict[i64,darray[Point]]"
assert functions["roundtrip"]["return"] == "dict[i64,darray[Point]]"
assert functions["roundtrip_rows"]["parameters"][0]["type"] == "darray[dict[i64,darray[Point]]]"
assert functions["roundtrip_rows"]["return"] == "darray[dict[i64,darray[Point]]]"
assert manifest["structs"][1]["fields"] == [{"name": "rows", "type": "dict[i64,darray[Point]]"}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/dict_darray_struct_values.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(rows: Mapping[int, Sequence[Point | PointInput]]) -> dict[int, list[Point]]: ...' "$WORK/dict_darray_struct_values.pyi"
grep -Fq 'def roundtrip_rows(rows: Sequence[Mapping[int, Sequence[Point | PointInput]]]) -> list[dict[int, list[Point]]]: ...' "$WORK/dict_darray_struct_values.pyi"
grep -Fq 'class Catalog(TypedDict):' "$WORK/dict_darray_struct_values.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dict_darray_struct_values.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_darray_struct_values.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_darray_struct_values as module

value = {1: [{"x": 7, "label": "α\x00β"}, {"x": -3, "label": "done"}], 2: []}
assert module.roundtrip(value) == value
rows = [{1: value[1]}, {}, {2: [{"x": 4, "label": "row"}]}]
assert module.roundtrip_rows(rows) == rows
assert module.roundtrip_catalog({"rows": value}) == {"rows": value}

for bad in ({1: [{"x": "bad", "label": "ok"}]}, {1: [{"x": 1}]}):
    try:
        module.roundtrip(bad)
    except (TypeError, KeyError):
        pass
    else:
        raise AssertionError(bad)

try:
    module.roundtrip_rows([{1: [{"x": "bad", "label": "ok"}]}])
except TypeError as exc:
    assert "at path [0][1][0].x:" in str(exc)
    assert exc.function == "roundtrip_rows"
    assert exc.parameter == "rows"
    assert exc.path == "[0][1][0].x"
else:
    raise AssertionError("nested dictionary/list/struct error did not include every path")

print("pymodule dictionary named-list values smoke OK")
PY
