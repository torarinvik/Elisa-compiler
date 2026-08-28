#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct nested lists smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/struct_nested_lists.json" \
    "$ROOT/test/repro/pymodule_struct_nested_lists.elisa" >/dev/null
python3 - "$WORK/struct_nested_lists.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["functions"] == [{
    "name": "roundtrip",
    "target": "roundtrip",
    "parameters": [{"name": "batch", "type": "NestedLists"}],
    "return": "NestedLists",
}]
assert manifest["structs"] == [{
    "name": "NestedPoint",
    "fields": [
        {"name": "x", "type": "i64"},
        {"name": "label", "type": "sview"},
    ],
}, {
    "name": "NestedLists",
    "fields": [
        {"name": "values", "type": "darray[darray[i64]]"},
        {"name": "cubes", "type": "darray[darray[darray[i64]]]"},
        {"name": "weights", "type": "darray[darray[f64]]"},
        {"name": "bytes", "type": "darray[darray[u8]]"},
        {"name": "texts", "type": "darray[darray[sview]]"},
        {"name": "labels", "type": "darray[darray[cstr]]"},
        {"name": "objects", "type": "darray[darray[py::Object]]"},
        {"name": "optional", "type": "darray[darray[i64?]]"},
        {"name": "points", "type": "darray[darray[NestedPoint]]"},
    ],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/struct_nested_lists.pyi" \
    "$ROOT/test/repro/pymodule_struct_nested_lists.elisa" >/dev/null
grep -Fq 'values: Sequence[Sequence[int]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'cubes: Sequence[Sequence[Sequence[int]]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'weights: Sequence[Sequence[float]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'bytes: Sequence[bytes | bytearray | memoryview]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'texts: Sequence[Sequence[str | bytes]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'labels: Sequence[Sequence[str | bytes]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'objects: Sequence[Sequence[Any]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'optional: Sequence[Sequence[int | None]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'points: Sequence[Sequence[NestedPoint | NestedPointInput]]' "$WORK/struct_nested_lists.pyi"
grep -Fq 'def roundtrip(batch: NestedLists | NestedListsInput) -> NestedLists: ...' "$WORK/struct_nested_lists.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/struct_nested_lists.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_nested_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_nested_lists.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_nested_lists

batch = {
    "values": [[1, -2], [], [3]],
    "cubes": [[[1, 2], []], [], [[3, -4]]],
    "weights": [[0.5, 1.25], [2.0]],
    "bytes": [b"abc", b"", bytes([0, 255])],
    "texts": [["α\x00β", "last"], []],
    "labels": [["first", "second"]],
    "objects": [[object(), None]],
    "optional": [[None, 7], []],
    "points": [[{"x": 1, "label": "α\x00β"}, {"x": -2, "label": "last"}], []],
}
result = struct_nested_lists.roundtrip(batch)
assert result == batch
assert result is not batch
assert result["values"] is not batch["values"]
assert result["values"][0] is not batch["values"][0]
assert result["bytes"] == batch["bytes"]
assert result["texts"] == batch["texts"]
assert result["labels"] == batch["labels"]
assert result["objects"][0][0] is batch["objects"][0][0]
assert result["objects"][0][1] is None
assert result["optional"] == batch["optional"]
assert result["points"] == batch["points"]

for bad in [
    {"values": [[1, "bad"]], "cubes": [], "weights": [], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [], "points": []},
    {"values": [1], "cubes": [], "weights": [], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [], "points": []},
    {"values": [[2**70]], "cubes": [], "weights": [], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [], "points": []},
    {"values": [], "cubes": [[1]], "weights": [], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [], "points": []},
    {"values": [], "cubes": [[[2**70]]], "weights": [], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [], "points": []},
    {"values": [], "cubes": [], "weights": [["bad"]], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [], "points": []},
    {"values": [], "cubes": [], "weights": [], "bytes": [], "texts": [], "labels": [["bad\x00label"]], "objects": [], "optional": [], "points": []},
    {"values": [], "cubes": [], "weights": [], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [[2**70]], "points": []},
    {"values": [], "cubes": [], "weights": [], "bytes": [], "texts": [], "labels": [], "objects": [], "optional": [], "points": [[{"x": "bad", "label": "ok"}]]},
]:
    try:
        struct_nested_lists.roundtrip(bad)
    except (OverflowError, TypeError, ValueError):
        pass
    else:
        raise AssertionError("invalid nested struct list was accepted")

try:
    struct_nested_lists.roundtrip({
        "values": [], "cubes": [[[2**70]]], "weights": [], "bytes": [],
        "texts": [], "labels": [], "objects": [], "optional": [], "points": [],
    })
except OverflowError as exc:
    assert "at path .cubes[0][0][0]:" in str(exc)
    assert exc.function == "roundtrip"
    assert exc.parameter == "batch"
    assert exc.path == ".cubes[0][0][0]"
else:
    raise AssertionError("deep struct list error did not include every list path")

print("pymodule struct nested lists smoke OK")
PY
