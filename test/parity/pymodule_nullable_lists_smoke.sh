#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable-list smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/nullable_lists.json" \
    "$ROOT/test/repro/pymodule_nullable_lists.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/nullable_lists.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert [row["parameters"][0]["type"] for row in manifest["functions"]] == [
    "darray[py::Object?]", "darray[cstr?]"
]
assert [row["return"] for row in manifest["functions"]] == [
    "darray[py::Object?]", "darray[cstr?]"
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nullable_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_nullable_lists.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nullable_lists

first = {"kind": "mapping"}
assert nullable_lists.optional_objects([first, None])[0] is first
assert nullable_lists.optional_objects([first, None])[1] is None
assert nullable_lists.optional_text(["hello", None, "på", "東京"]) == ["hello", None, "på", "東京"]
try:
    nullable_lists.optional_text(["ok\x00bad"])
except ValueError:
    pass
else:
    raise AssertionError("nullable cstr list should reject embedded NUL bytes")
PY

echo "pymodule nullable-list smoke OK"
