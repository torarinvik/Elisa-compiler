#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct-nested-dict-darrays smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" \
    "$ROOT/test/repro/pymodule_struct_nested_dict_darrays.elisa" >/dev/null
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/module.pyi" \
    "$ROOT/test/repro/pymodule_struct_nested_dict_darrays.elisa" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert manifest["structs"] == [{
    "name": "Payload",
    "fields": [{"name": "values", "type": "dict[i64,darray[darray[i64]]]"}],
}]
assert manifest["functions"] == [{
    "name": "roundtrip",
    "target": "roundtrip",
    "parameters": [{"name": "value", "type": "Payload"}],
    "return": "Payload",
}]
PY
python3 - "$WORK/module.pyi" <<'PY'
import sys

stub = open(sys.argv[1], encoding="utf-8").read()
assert "values: dict[int, list[list[int]]]" in stub
assert "values: Mapping[int, Sequence[Sequence[int]]]" in stub
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_nested_dict_darrays.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_nested_dict_darrays.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_nested_dict_darrays

value = {"values": {1: [[2, 3], []], 4: [[5], [6, 7]]}}
assert struct_nested_dict_darrays.roundtrip(value) == value

for bad in (
    {"values": {1: [2]}},
    {"values": {1: [[2**70]]}},
):
    try:
        struct_nested_dict_darrays.roundtrip(bad)
    except (TypeError, OverflowError):
        pass
    else:
        raise AssertionError("invalid nested dictionary struct value was accepted")

print("pymodule struct nested dictionary darrays smoke OK")
PY
