#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional-payload-errors smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/optional_payload_errors.json" \
    "$ROOT/test/repro/pymodule_optional_payload_errors.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/optional_payload_errors.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
rows = {row["name"]: row for row in manifest["functions"]}
assert rows["fail_int"]["payload"] == "i64?"
assert rows["fail_text"]["payload"] == "sview?"
assert rows["fail_cstr"]["payload"] == "cstr?"
assert rows["fail_object"]["payload"] == "py::Object?"
assert rows["fail_struct"]["payload"] == "struct"
fields = rows["fail_struct"]["payload_variants"][0]["fields"]
assert [field["type"] for field in fields[1:]] == ["i64?", "sview?", "py::Object?", "cstr?"]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_payload_errors.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_optional_payload_errors.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import optional_payload_errors as module

def raised(function, *values):
    try:
        function(*values)
    except module.ElisaError as error:
        return error.payload
    raise AssertionError("expected ElisaError")

assert raised(module.fail_int, None) is None
assert raised(module.fail_int, 5) == 5
assert raised(module.fail_text, None) is None
assert raised(module.fail_text, "hé") == "hé"
assert raised(module.fail_cstr, None) is None
assert raised(module.fail_cstr, "hé") == "hé"

value = {"ok": True}
assert raised(module.fail_object, None) is None
assert raised(module.fail_object, value) is value
assert raised(module.fail_struct, None) == {"variant": "Invalid", "code": 7, "value": None, "label": None, "object": None, "text": None}
value = {"ok": True}
assert raised(module.fail_struct, 9, "hé", value, "wørld") == {"variant": "Invalid", "code": 7, "value": 9, "label": "hé", "object": value, "text": "wørld"}
PY

echo "pymodule optional-payload-errors smoke OK"
