#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule darray-dict smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" \
    "$ROOT/test/repro/pymodule_darray_dict_probe.elisa" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["roundtrip"]["parameters"][0]["type"] == "darray[dict[i64,i64]]"
assert functions["roundtrip"]["return"] == "darray[dict[i64,i64]]"
assert functions["roundtrip_rows"]["parameters"][0]["type"] == "darray[dict[i64,Row]]"
assert functions["roundtrip_rows"]["return"] == "darray[dict[i64,Row]]"
assert functions["roundtrip_nested"]["parameters"][0]["type"] == "darray[dict[i64,dict[cstr,i64]]]"
assert functions["roundtrip_nested"]["return"] == "darray[dict[i64,dict[cstr,i64]]]"
assert functions["count"]["parameters"][0]["type"] == "darray[dict[i64,i64]]"
assert manifest["structs"] == [{"name": "Row", "fields": [{"name": "value", "type": "i64"}]}]
PY

# A list of dictionaries owns both a temporary Python sequence/buffer and the nested dictionary
# arena/reference table. Keep all four releases in generated C so aggregate ownership cannot
# regress when the element spelling is generic rather than a named struct.
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/darray_dict_probe.c" "$ROOT/test/repro/pymodule_darray_dict_probe.elisa" >/dev/null
grep -Fq 'Py_XDECREF(arg0_seq);' "$WORK/darray_dict_probe.c"
grep -Fq 'PyMem_Free(arg0_items);' "$WORK/darray_dict_probe.c"
grep -Fq 'elisa_pymodule_struct_refs_free(&arg0_struct_refs);' "$WORK/darray_dict_probe.c"
grep -Fq 'arena_free(&arg0_struct_arena);' "$WORK/darray_dict_probe.c"

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/darray_dict_probe.pyi" "$ROOT/test/repro/pymodule_darray_dict_probe.elisa" >/dev/null
grep -Fq 'def roundtrip(values: Sequence[Mapping[int, int]]) -> list[dict[int, int]]: ...' "$WORK/darray_dict_probe.pyi"
grep -Fq 'def roundtrip_rows(values: Sequence[Mapping[int, Row | RowInput]]) -> list[dict[int, Row]]: ...' "$WORK/darray_dict_probe.pyi"
grep -Fq 'def roundtrip_nested(values: Sequence[Mapping[int, Mapping[str | bytes, int]]]) -> list[dict[int, dict[str, int]]]: ...' "$WORK/darray_dict_probe.pyi"
grep -Fq 'def count(values: Sequence[Mapping[int, int]]) -> int: ...' "$WORK/darray_dict_probe.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/darray_dict_probe.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/darray_dict_probe.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_darray_dict_probe.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import darray_dict_probe

value = [{1: 2, 3: -4}, {}]
assert darray_dict_probe.roundtrip(value) == value
assert darray_dict_probe.roundtrip([]) == []
assert darray_dict_probe.count(value) == 2
rows = [{1: {"value": 2}}, {}]
assert darray_dict_probe.roundtrip_rows(rows) == rows
nested = [{1: {"a": 2, "b": -3}}, {}]
assert darray_dict_probe.roundtrip_nested(nested) == nested

for bad in ([{1: "not an integer"}], [1], {"x": 1}):
    try:
        darray_dict_probe.roundtrip(bad)
    except (TypeError, OverflowError):
        pass
    else:
        raise AssertionError(bad)

print("pymodule darray dictionary smoke OK")
PY
