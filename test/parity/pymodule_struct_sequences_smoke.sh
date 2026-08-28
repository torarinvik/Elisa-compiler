#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct sequences smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

# Some checkout-local runtime objects intentionally leave the optional native callback host
# unresolved.  Do not turn that unrelated linker setup into a false negative for this ABI smoke.
if nm -u "$ROOT/build/runtime/elisacore_runtime.o" 2>/dev/null | grep -q 'elisa_native_callback_'; then
    echo "pymodule struct sequences smoke SKIP (runtime callback host unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/struct_sequences.json" \
    "$ROOT/test/repro/pymodule_struct_sequences.elisa" >/dev/null
python3 - "$WORK/struct_sequences.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["functions"] == [
    {
        "name": "roundtrip_points",
        "target": "roundtrip_points",
        "parameters": [{"name": "points", "type": "darray[Point]"}],
        "return": "darray[Point]",
    },
    {
        "name": "count_points",
        "target": "count_points",
        "parameters": [{"name": "points", "type": "view[Point]"}],
        "return": "usize",
    },
    {
        "name": "identity_points",
        "target": "identity_points",
        "parameters": [{"name": "points", "type": "view[Point]"}],
        "return": "view[Point]",
    },
]
assert manifest["structs"] == [{
    "name": "Point",
    "fields": [
        {"name": "x", "type": "i64"},
        {"name": "label", "type": "sview"},
        {"name": "payload", "type": "py::Object"},
    ],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/struct_sequences.pyi" \
    "$ROOT/test/repro/pymodule_struct_sequences.elisa" >/dev/null
grep -Fq 'class Point(TypedDict):' "$WORK/struct_sequences.pyi"
grep -Fq 'class PointInput(Protocol):' "$WORK/struct_sequences.pyi"
grep -Fq 'def roundtrip_points(points: Sequence[Point | PointInput]) -> list[Point]: ...' "$WORK/struct_sequences.pyi"
grep -Fq 'def count_points(points: Sequence[Point | PointInput]) -> int: ...' "$WORK/struct_sequences.pyi"
grep -Fq 'def identity_points(points: Sequence[Point | PointInput]) -> list[Point]: ...' "$WORK/struct_sequences.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_sequences.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_sequences.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_sequences.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_sequences

payload = {"kind": "point"}
points = [
    {"x": 1, "label": "α\x00β", "payload": payload},
    {"x": -2, "label": "last", "payload": None},
]
assert struct_sequences.roundtrip_points(points) == points
assert struct_sequences.roundtrip_points(points)[0]["payload"] is payload
assert struct_sequences.count_points(points) == 2
assert struct_sequences.identity_points(points) == points
assert struct_sequences.identity_points(points)[0]["payload"] is payload

for bad in (
    [{"x": "not an integer", "label": "ok", "payload": None}],
    [{"x": 1, "label": 42, "payload": None}],
    [{"x": 1, "label": "ok"}],
):
    try:
        struct_sequences.roundtrip_points(bad)
    except (KeyError, TypeError):
        pass
    else:
        raise AssertionError("invalid struct sequence element accepted")

print("pymodule struct sequences smoke OK")
PY

# The same bridge also composes inside a returned/input struct, so nested records do not
# regress when a field changes from `Point` to `darray[Point]` or `view[Point]`.
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_sequence_fields.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_sequence_fields.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_sequence_fields

batch = {
    "points": [{"x": 1}, {"x": 2}],
    "view_points": [{"x": 3}, {"x": 4}],
    "rows": [{1: 10, 2: 20}, {}],
    "point_rows": [{1: {"x": 5}}, {2: {"x": -6}}],
    "nested_rows": {7: [{"x": 8}, {}]},
}
assert struct_sequence_fields.roundtrip_batch(batch) == batch
for bad in (
    {"points": [{"x": "bad"}], "view_points": [], "rows": [], "point_rows": [], "nested_rows": {}},
    {"points": [], "view_points": [{"x": "bad"}], "rows": [], "point_rows": [], "nested_rows": {}},
    {"points": [], "view_points": [], "rows": [{"bad": 1}], "point_rows": [], "nested_rows": {}},
    {"points": [], "view_points": [], "rows": [], "point_rows": [{1: {"x": "bad"}}], "nested_rows": {}},
    {"points": [], "view_points": [], "rows": [], "point_rows": [], "nested_rows": {7: [{"x": "bad"}]}},
):
    try:
        struct_sequence_fields.roundtrip_batch(bad)
    except TypeError:
        pass
    else:
        raise AssertionError("invalid nested struct sequence accepted")

print("pymodule nested struct sequences smoke OK")
PY
