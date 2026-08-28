#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dict struct values smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_dict_struct_values.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["functions"] == [
    {
        "name": "roundtrip",
        "target": "roundtrip",
        "parameters": [{"name": "values", "type": "dict[cstr,Point]"}],
        "return": "dict[cstr,Point]",
    },
    {
        "name": "roundtrip_catalog",
        "target": "roundtrip_catalog",
        "parameters": [{"name": "catalog", "type": "Catalog"}],
        "return": "Catalog",
    },
]
assert manifest["structs"] == [
    {
        "name": "Point",
        "fields": [{"name": "x", "type": "i64"}, {"name": "label", "type": "sview"}],
    },
    {
        "name": "Catalog",
        "fields": [{"name": "values", "type": "dict[cstr,Point]"}],
    },
]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/dict_struct_values.pyi" "$SOURCE" >/dev/null
grep -Fq 'class Point(TypedDict):' "$WORK/dict_struct_values.pyi"
grep -Fq 'class PointInput(Protocol):' "$WORK/dict_struct_values.pyi"
grep -Fq 'class Catalog(TypedDict):' "$WORK/dict_struct_values.pyi"
grep -Fq 'class CatalogInput(Protocol):' "$WORK/dict_struct_values.pyi"
grep -Fq 'def roundtrip(values: Mapping[str | bytes, Point | PointInput]) -> dict[str, Point]: ...' "$WORK/dict_struct_values.pyi"
grep -Fq 'def roundtrip_catalog(catalog: Catalog | CatalogInput) -> Catalog: ...' "$WORK/dict_struct_values.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dict_struct_values.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_struct_values.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_struct_values

payload = {"first": {"x": 1, "label": "α\x00β"}, "last": {"x": -2, "label": "done"}}
assert dict_struct_values.roundtrip(payload) == payload
assert dict_struct_values.roundtrip_catalog({"values": payload}) == {"values": payload}

for bad in (
    {"first": {"x": "not an integer", "label": "ok"}},
    {"first": {"x": 1, "label": 42}},
    {"first": {"x": 1}},
):
    try:
        dict_struct_values.roundtrip(bad)
    except (KeyError, TypeError):
        pass
    else:
        raise AssertionError("invalid dictionary struct value accepted")

print("pymodule dict struct values smoke OK")
PY
