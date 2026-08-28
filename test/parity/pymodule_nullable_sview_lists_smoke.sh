#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable-sview-list smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/nullable_sview_lists.json" \
    "$ROOT/test/repro/pymodule_nullable_sview_lists.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/nullable_sview_lists.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
row = manifest["functions"][0]
assert row["parameters"][0]["type"] == "darray[sview?]"
assert row["return"] == "darray[sview?]"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nullable_sview_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_nullable_sview_lists.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nullable_sview_lists

values = ["hello\x00på", None, "東京\x00value"]
assert nullable_sview_lists.optional_text(values) == values
assert nullable_sview_lists.optional_text([b"hello", None, b"\xce\xb1"]) == ["hello", None, "α"]
try:
    nullable_sview_lists.optional_text([b"\xff"])
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("nullable sview list should reject invalid UTF-8 bytes")
PY

echo "pymodule nullable-sview-list smoke OK"
