#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nested dictionary error payload smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/error_payload_nested_dict.json" \
    "$ROOT/test/repro/pymodule_error_payload_nested_dict.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/error_payload_nested_dict.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
function = functions["fail_nested"]
assert function["raises"] == "NestedDictPayloadError"
assert function["payload"] == "dict[i64,dict[cstr,i64]]"
structured = functions["fail_structured"]
assert structured["raises"] == "StructuredNestedDictPayloadError"
assert structured["payload"] == "struct"
assert structured["payload_variants"] == [{
    "name": "Bad",
    "fields": [
        {"name": "code", "type": "i64"},
        {"name": "values", "type": "dict[i64,dict[cstr,i64]]"},
    ],
}]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_nested_dict.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_nested_dict.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_nested_dict

values = {1: {"a": 2, "b": -3}, 4: {}, 7: {"z": 11}}
try:
    error_payload_nested_dict.fail_nested(values)
except error_payload_nested_dict.ElisaError as exc:
    assert exc.function == "fail_nested"
    assert exc.payload == values
else:
    raise AssertionError("nested dictionary error payload should raise ElisaError")

try:
    error_payload_nested_dict.fail_structured(17, values)
except error_payload_nested_dict.ElisaError as exc:
    assert exc.payload == {"variant": "Bad", "code": 17, "values": values}
else:
    raise AssertionError("structured nested dictionary error payload should raise ElisaError")

try:
    error_payload_nested_dict.fail_nested({1: {"a": 2**80}})
except OverflowError:
    pass
else:
    raise AssertionError("nested dictionary error payload should preserve integer range checks")
PY

echo "pymodule nested dictionary error payload smoke OK"
