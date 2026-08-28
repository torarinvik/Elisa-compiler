#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional-pointer-errors smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/optional_pointer_errors.json" \
    "$ROOT/test/repro/pymodule_optional_pointer_errors.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/optional_pointer_errors.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
rows = {row["name"]: row for row in manifest["functions"]}
assert rows["text"]["parameters"] == [{"name": "value", "type": "i64"}]
assert rows["text"]["return"] == "cstr?"
assert rows["object"]["parameters"] == [{"name": "value", "type": "py::Object?", "default": "None"}]
assert rows["object"]["return"] == "py::Object?"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_pointer_errors.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_optional_pointer_errors.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import optional_pointer_errors

assert optional_pointer_errors.text(3) == "ready"
assert optional_pointer_errors.text(0) is None
assert str(inspect.signature(optional_pointer_errors.text)) == "(value)"

value = {"ok": True}
assert optional_pointer_errors.object(value) is value
assert optional_pointer_errors.object(value=value) is value
assert optional_pointer_errors.object() is None
assert str(inspect.signature(optional_pointer_errors.object)) == "(value=None)"

for function, value in ((optional_pointer_errors.text, -1),):
    try:
        function(value)
    except Exception as error:
        assert isinstance(error, optional_pointer_errors.MaybePointerError)
        assert isinstance(error, optional_pointer_errors.ElisaError)
        assert error.code != 0
        assert error.function in ("text", "maybe_text")
    else:
        raise AssertionError("negative text input should raise ElisaError")

assert optional_pointer_errors.object(None) is None
PY

echo "pymodule optional-pointer-errors smoke OK"
