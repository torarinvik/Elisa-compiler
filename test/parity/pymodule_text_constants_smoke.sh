#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule text constants smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/text_constants.json" \
    "$ROOT/test/repro/pymodule_text_constants.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/text_constants.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
assert manifest["module"] == "text_constants"
assert manifest["constants"] == [
    {"name": "greeting", "target": "GREETING", "type": "cstr"},
    {"name": "label", "target": "LABEL", "type": "sview"},
    {"name": "bytes", "target": "BYTES", "type": "darray[u8]"},
    {"name": "inferred", "target": "INFERRED_TEXT", "type": "cstr"},
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/text_constants.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_text_constants.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import text_constants

assert text_constants.greeting == "hello\nworld"
assert text_constants.label == "label\x00tail"
assert text_constants.bytes == b"A\x00B"
assert text_constants.inferred == "inferred"
assert text_constants.__all__ == ["greeting", "label", "bytes", "inferred", "ElisaError"]
PY

echo "pymodule text constants smoke OK"
