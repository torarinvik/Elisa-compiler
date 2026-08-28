#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule structured dictionary error payload smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/error_payload_struct_dict.json" \
    "$ROOT/test/repro/pymodule_error_payload_struct_dict.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/error_payload_struct_dict.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail_dict"]["payload"] == "struct"
assert functions["fail_dict"]["payload_variants"] == [{
    "name": "Bad",
    "fields": [
        {"name": "code", "type": "i64"},
        {"name": "values", "type": "dict[i64,i64]"},
    ],
}]
assert functions["fail_text"]["payload_variants"][0]["fields"][1] == {
    "name": "values", "type": "dict[sview,sview]"
}
PY

# Structured dictionary fields use a private copier arena. The generated success handoff must
# release that arena, while malformed/allocation failures must release it exactly once together
# with the enclosing error arena.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/error_payload_struct_dict.c" \
    "$ROOT/test/repro/pymodule_error_payload_struct_dict.elisa" >/dev/null
python3 - "$WORK/error_payload_struct_dict.c" <<'PY'
import sys

source = open(sys.argv[1], encoding="utf-8").read()
start = source.index("static PyObject *elisa_py_fail_dict")
end = source.index("static const char *elisa_pymodule_struct_names", start)
wrapper = source[start:end]
# Structured payload conversion is guarded by one wrapper-owned cleanup label.  Normalize
# whitespace because generated snippets intentionally remain compact, then assert that field
# arenas funnel through the shared payload-failure path rather than returning early and risking
# a leak or a double free of the enclosing arena.
normalized = " ".join(wrapper.split())
assert "elisa_pymodule_error_dict_field_failed_1:" in wrapper
assert "arena_free(&field_arena); field_object = field_out; goto elisa_pymodule_error_dict_field_done_1;" in normalized
assert "elisa_pymodule_error_dict_field_failed_1:; arena_free(&field_arena); goto elisa_pymodule_error_payload_conversion_failed;" in normalized
assert "elisa_pymodule_error_payload_conversion_failed:" in wrapper
assert "arena_free(&arena); return NULL;" in normalized
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_struct_dict.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_error_payload_struct_dict.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_struct_dict

try:
    error_payload_struct_dict.fail_dict(7, {1: 2, 3: 4})
except error_payload_struct_dict.ElisaError as exc:
    assert exc.payload == {"variant": "Bad", "code": 7, "values": {1: 2, 3: 4}}
else:
    raise AssertionError("structured dictionary payload should raise ElisaError")

try:
    error_payload_struct_dict.fail_text("hé", {"wørld": "ok", "a": "b"})
except error_payload_struct_dict.ElisaError as exc:
    assert exc.payload == {
        "variant": "Bad",
        "label": "hé",
        "values": {"wørld": "ok", "a": "b"},
    }
else:
    raise AssertionError("structured text dictionary payload should raise ElisaError")
PY

echo "pymodule structured dictionary error payload smoke OK"
