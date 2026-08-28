#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct defaults smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/struct_defaults.json" \
    "$ROOT/test/repro/pymodule_struct_defaults.elisa" >/dev/null
python3 - "$WORK/struct_defaults.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
config = next(struct for struct in manifest["structs"] if struct["name"] == "Config")
fields = {field["name"]: field for field in config["fields"]}
assert fields["numbers"]["default"] == "[1, 2]"
assert fields["bytes"]["default"] == 'b"\\x01\\x02\\xff"'
assert fields["mapping"]["default"] == "{1: 2}"
assert fields["unique"]["default"] == "{3, 4}"
assert fields["nested"]["default"] == "[[7], [8, 9]]"
assert fields["origin"]["default"] == '{"x": 10, "y": 20}'
function = next(function for function in manifest["functions"] if function["name"] == "point_roundtrip")
assert function["parameters"][0]["default"] == '{"x": 10, "y": 20}'
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/struct_defaults.pyi" \
    "$ROOT/test/repro/pymodule_struct_defaults.elisa" >/dev/null
grep -F 'def point_roundtrip(point: Point | PointInput = {"x": 10, "y": 20}) -> Point: ...' "$WORK/struct_defaults.pyi" >/dev/null

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_defaults.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_defaults.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_defaults
from types import SimpleNamespace

defaults = {
    "retries": 3,
    "enabled": True,
    "ratio": 0.5,
    "label": "guest",
    "text": "hello",
    "tags": [],
    "numbers": [1, 2],
    "bytes": b"\x01\x02\xff",
    "mapping": {1: 2},
    "unique": {3, 4},
    "view_values": [5, 6],
    "nested": [[7], [8, 9]],
    "origin": {"x": 10, "y": 20},
}
assert struct_defaults.roundtrip({}) == defaults
assert struct_defaults.roundtrip({"retries": 9}) == {
    **defaults,
    "retries": 9,
}
assert struct_defaults.roundtrip(SimpleNamespace(enabled=False, text="world")) == {
    **defaults,
    "enabled": False,
    "text": "world",
}
assert struct_defaults.roundtrip({"tags": [4, 5]}) == {
    **defaults,
    "tags": [4, 5],
}
assert struct_defaults.roundtrip({"numbers": [10], "mapping": {11: 12}, "unique": {13}, "view_values": [14], "nested": [[15]]}) == {
    **defaults,
    "numbers": [10],
    "mapping": {11: 12},
    "unique": {13},
    "view_values": [14],
    "nested": [[15]],
}
assert struct_defaults.roundtrip({"origin": {"x": -1, "y": 2}}) == {
    **defaults,
    "origin": {"x": -1, "y": 2},
}
assert struct_defaults.point_roundtrip() == {"x": 10, "y": 20}
assert struct_defaults.point_roundtrip({"x": -5, "y": 6}) == {"x": -5, "y": 6}
fresh = struct_defaults.point_roundtrip()
fresh["x"] = 999
assert struct_defaults.point_roundtrip() == {"x": 10, "y": 20}
print("pymodule struct defaults smoke OK")
PY
