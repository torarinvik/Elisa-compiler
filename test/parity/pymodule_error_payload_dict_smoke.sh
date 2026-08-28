#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule dictionary error payload smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/error_payload_dict.json" \
    "$ROOT/test/repro/pymodule_error_payload_dict.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/error_payload_dict.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert manifest["module"] == "error_payload_dict"
assert [row["name"] for row in manifest["functions"]] == [
    "fail_dict", "fail_text", "fail_objects"
]
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail_dict"]["raises"] == "DictPayloadError"
assert functions["fail_dict"]["payload"] == "dict[i64,i64]"
assert functions["fail_text"]["raises"] == "TextDictPayloadError"
assert functions["fail_text"]["payload"] == "dict[sview,sview]"
assert functions["fail_objects"]["raises"] == "ObjectDictPayloadError"
assert functions["fail_objects"]["payload"] == "dict[i64,py::Object]"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_dict.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_dict.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_dict

assert error_payload_dict.__all__ == [
    "fail_dict", "fail_text", "fail_objects", "DictPayloadError", "TextDictPayloadError", "ObjectDictPayloadError", "ElisaError"
]

try:
    error_payload_dict.fail_dict({1: 2, 3: 4})
except error_payload_dict.ElisaError as exc:
    assert isinstance(exc, error_payload_dict.DictPayloadError)
    assert exc.function == "fail_dict"
    assert exc.payload == {1: 2, 3: 4}
else:
    raise AssertionError("dictionary payload should raise ElisaError")

try:
    error_payload_dict.fail_text({"héllo": "wørld", "a": "b"})
except error_payload_dict.ElisaError as exc:
    assert isinstance(exc, error_payload_dict.TextDictPayloadError)
    assert exc.function == "fail_text"
    assert exc.payload == {"héllo": "wørld", "a": "b"}
else:
    raise AssertionError("text dictionary payload should raise ElisaError")

obj = {"kept": True}
try:
    error_payload_dict.fail_objects({1: obj})
except error_payload_dict.ElisaError as exc:
    assert isinstance(exc, error_payload_dict.ObjectDictPayloadError)
    assert exc.function == "fail_objects"
    assert exc.payload[1] is obj
else:
    raise AssertionError("object dictionary payload should raise ElisaError")
PY

echo "pymodule dictionary error payload smoke OK"
