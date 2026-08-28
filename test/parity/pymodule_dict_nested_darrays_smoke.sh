#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dictionary nested darrays smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_dict_nested_darrays.elisa"
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
"$PYTHON_BIN" - "$WORK/manifest.json" <<'PY'
import json, sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
rows = {row["name"]: row for row in manifest["functions"]}
assert rows["roundtrip"]["parameters"] == [{"name": "values", "type": "dict[i64,darray[darray[i64]]]"}]
assert rows["roundtrip"]["return"] == "dict[i64,darray[darray[i64]]]"
assert rows["roundtrip_text"]["return"] == "dict[cstr,darray[darray[sview]]]"
assert rows["roundtrip_objects"]["return"] == "dict[i64,darray[darray[py::Object]]]"
assert rows["roundtrip_deep"]["return"] == "dict[i64,darray[darray[darray[darray[i64]]]]]"
assert rows["roundtrip_rows"]["parameters"] == [{"name": "values", "type": "dict[i64,darray[dict[cstr,i64]]]"}]
assert rows["roundtrip_rows"]["return"] == "dict[i64,darray[dict[cstr,i64]]]"
assert rows["roundtrip_batches"]["parameters"] == [{"name": "values", "type": "darray[dict[i64,darray[dict[cstr,i64]]]]"}]
assert rows["roundtrip_batches"]["return"] == "darray[dict[i64,darray[dict[cstr,i64]]]]"
assert rows["fail"]["return"] == "i64"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/dict_nested_darrays.pyi" "$SOURCE" >/dev/null
grep -Fq 'def roundtrip(values: Mapping[int, Sequence[Sequence[int]]]) -> dict[int, list[list[int]]]: ...' "$WORK/dict_nested_darrays.pyi"
grep -Fq 'def roundtrip_text(values: Mapping[str | bytes, Sequence[Sequence[str | bytes]]]) -> dict[str, list[list[str]]]: ...' "$WORK/dict_nested_darrays.pyi"
grep -Fq 'def roundtrip_objects(values: Mapping[int, Sequence[Sequence[Any]]]) -> dict[int, list[list[Any]]]: ...' "$WORK/dict_nested_darrays.pyi"
grep -Fq 'def roundtrip_deep(values: Mapping[int, Sequence[Sequence[Sequence[Sequence[int]]]]]) -> dict[int, list[list[list[list[int]]]]]: ...' "$WORK/dict_nested_darrays.pyi"
grep -Fq 'def roundtrip_rows(values: Mapping[int, Sequence[Mapping[str | bytes, int]]]) -> dict[int, list[dict[str, int]]]: ...' "$WORK/dict_nested_darrays.pyi"
grep -Fq 'def roundtrip_batches(values: Sequence[Mapping[int, Sequence[Mapping[str | bytes, int]]]]) -> list[dict[int, list[dict[str, int]]]]: ...' "$WORK/dict_nested_darrays.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/dict_nested_darrays.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/dict_nested_darrays.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import dict_nested_darrays

payload = {1: [[1, 2], [], [3]], 8: []}
assert dict_nested_darrays.roundtrip(payload) == payload
text_payload = {"alpha": [["x\x00y"], []]}
assert dict_nested_darrays.roundtrip_text(text_payload) == text_payload
obj = object()
object_payload = {4: [[obj, None], []]}
returned_objects = dict_nested_darrays.roundtrip_objects(object_payload)
assert returned_objects[4][0][0] is obj and returned_objects[4][0][1] is None
deep_payload = {2: [[[[1], []]], []], 7: []}
assert dict_nested_darrays.roundtrip_deep(deep_payload) == deep_payload
rows_payload = {3: [{"x": 1, "y": -2}, {}], 9: []}
assert dict_nested_darrays.roundtrip_rows(rows_payload) == rows_payload
batches_payload = [{4: [{"x": 7}, {}]}, {}]
assert dict_nested_darrays.roundtrip_batches(batches_payload) == batches_payload
try:
    dict_nested_darrays.fail(payload)
except dict_nested_darrays.ElisaError as exc:
    assert exc.payload == payload
else:
    raise AssertionError("expected nested dictionary payload error")

for bad in ({1: [[1, "bad"]]}, {1: None}, {1: [[2**63]]}, {1: [{"x": "bad"}]}):
    try:
        (dict_nested_darrays.roundtrip(bad) if bad != {1: [{"x": "bad"}]} else dict_nested_darrays.roundtrip_rows(bad))
    except (OverflowError, TypeError, ValueError):
        pass
    else:
        raise AssertionError(f"invalid nested dictionary value accepted: {bad!r}")

print("pymodule dictionary nested darrays smoke OK")
PY
