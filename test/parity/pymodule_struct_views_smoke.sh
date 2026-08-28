#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct views smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/struct_views.json" \
    "$ROOT/test/repro/pymodule_struct_views.elisa" >/dev/null
python3 - "$WORK/struct_views.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert manifest["structs"] == [{
    "name": "ViewBatch",
    "fields": [
        {"name": "values", "type": "view[i64]"},
        {"name": "text", "type": "view[sview]"},
        {"name": "objects", "type": "view[py::Object]"},
        {"name": "bytes", "type": "view[u8]"},
    ],
}]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_views.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_views.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import gc

import struct_views

payload = {"kind": "view"}
batch = {"values": [1, 2, 3], "text": ["α", "β"], "objects": [payload, None], "bytes": [65, 66, 67]}
result = struct_views.roundtrip(batch)
assert result["values"] == batch["values"]
assert result["text"] == batch["text"]
assert result["bytes"] == b"ABC"
assert result["objects"][0] is payload
assert struct_views.total(batch) == 6
assert struct_views.roundtrip({"values": [1], "text": [b"\xce\xb1"], "objects": [], "bytes": []})["text"] == ["α"]

class Ephemeral:
    def __getattr__(self, name):
        values = {"values": [4, 5], "text": ["fresh-text"], "objects": [payload], "bytes": [120, 121]}
        return list(values[name])

result = struct_views.roundtrip(Ephemeral())
gc.collect()
assert result["values"] == [4, 5]
assert result["text"] == ["fresh-text"]
assert result["objects"][0] is payload
assert result["bytes"] == b"xy"

for bad in ({"values": [1], "text": [], "objects": [], "bytes": [256]}, batch | {"values": ["nope"]}):
    try:
        struct_views.roundtrip(bad)
    except (TypeError, OverflowError):
        pass
    else:
        raise AssertionError("invalid view struct accepted")
PY

echo "pymodule struct views smoke OK"
