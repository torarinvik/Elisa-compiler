#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule nullable-dict smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/nullable_dicts.json" \
    "$ROOT/test/repro/pymodule_nullable_dicts.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/nullable_dicts.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert [row["parameters"][0]["type"] for row in manifest["functions"]] == [
    "dict[cstr,py::Object?]", "dict[cstr,cstr?]", "dict[cstr,sview?]"
]
assert [row["return"] for row in manifest["functions"]] == [
    "dict[cstr,py::Object?]", "dict[cstr,cstr?]", "dict[cstr,sview?]"
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/nullable_dicts.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_nullable_dicts.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import nullable_dicts

obj = {"kind": "payload"}
assert nullable_dicts.optional_objects({"object": obj, "empty": None})["object"] is obj
assert nullable_dicts.optional_objects({"object": obj, "empty": None})["empty"] is None
assert nullable_dicts.optional_text({"hello": "på", "empty": None, "東京": "value"}) == {
    "hello": "på", "empty": None, "東京": "value"
}
assert nullable_dicts.optional_view({"hello": "på", "empty": None, "nul": "a\x00b"}) == {
    "hello": "på", "empty": None, "nul": "a\x00b"
}
try:
    nullable_dicts.optional_text({"bad": "ok\x00bad"})
except ValueError:
    pass
else:
    raise AssertionError("nullable cstr dictionary values should reject embedded NUL bytes")
try:
    nullable_dicts.optional_text({"bad": 42})
except TypeError:
    pass
else:
    raise AssertionError("nullable cstr dictionary values should reject non-str values")
PY

echo "pymodule nullable-dict smoke OK"
