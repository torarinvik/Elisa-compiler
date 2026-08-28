#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule struct codegen names smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

for fixture in struct_codegen_names struct_codegen_nested_names; do
    PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
        bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
        -o "$WORK/${fixture}.cpython-314-darwin.so" \
        "$ROOT/test/repro/pymodule_${fixture}.elisa" >/dev/null
done

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_codegen_names
import struct_codegen_nested_names

object_value = object()
names = {
    "arena": {1: 2}, "result": {3: 4}, "field_value": [5, 6], "field_seq": [7, 8],
    "field_view": [9], "payload": {10, 11}, "items": [12], "count": 13, "value": 14,
    "object": object_value, "key": "hello", "index": 15, "error_type": 16,
    "error_value": 17, "error_traceback": 18, "owned": 19, "result_index": 20,
    "nested_index": 21, "list": [22], "view": [23, 24],
}
roundtripped = struct_codegen_names.roundtrip(names)
assert roundtripped == names
assert roundtripped["object"] is object_value

nested_object = object()
nested = {
    "result": {1: [2, None]},
    "result_index": {3: [4.5, None]},
    "nested_index": {5: [nested_object, None]},
}
nested_result = struct_codegen_nested_names.roundtrip(nested)
assert nested_result["result"] == nested["result"]
assert nested_result["result_index"] == nested["result_index"]
assert nested_result["nested_index"][5][0] is nested_object
print("pymodule struct codegen names smoke OK")
PY
