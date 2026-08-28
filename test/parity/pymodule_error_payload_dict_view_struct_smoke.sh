#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule named-record view error payload smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_error_payload_dict_view_struct.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

function = json.load(open(sys.argv[1], encoding="utf-8"))["functions"][0]
assert function["parameters"][0]["type"] == "dict[i64,view[Point]]"
assert function["raises"] == "RowsError"
assert function["payload"] == "dict[i64,view[Point]]"
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/error_payload_dict_view_struct.pyi" "$SOURCE" >/dev/null
grep -Fq 'class RowsError(ElisaError):' "$WORK/error_payload_dict_view_struct.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_dict_view_struct.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_dict_view_struct.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_dict_view_struct as module

value = {1: [{"x": 3, "label": "a"}, {"x": -2, "label": "β"}]}
try:
    module.fail(value)
except module.RowsError as error:
    assert error.payload == value
    assert error.payload is not value
else:
    raise AssertionError("fail() did not raise RowsError")

print("pymodule named-record view error payload smoke OK")
PY
