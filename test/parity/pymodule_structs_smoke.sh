#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule structs smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/structs.json" \
    "$ROOT/test/repro/pymodule_structs.elisa" >/dev/null
python3 - "$WORK/structs.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert manifest["structs"] == [{
    "name": "Point",
    "fields": [
        {"name": "x", "type": "i64"},
        {"name": "small", "type": "i32"},
        {"name": "y", "type": "f64"},
        {"name": "ratio", "type": "f32"},
        {"name": "label", "type": "cstr"},
        {"name": "text", "type": "sview"},
        {"name": "flag", "type": "bool"},
        {"name": "payload", "type": "py::Object"},
    ],
}]
PY

# Direct struct inputs must use the cleanup-aware scalar-return path.  The old
# expression fast path returned `score` immediately and leaked its struct arena
# and retained Python references on every successful call.
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/structs.c" \
    "$ROOT/test/repro/pymodule_structs.elisa" >/dev/null
python3 - "$WORK/structs.c" <<'PY'
import sys

source = open(sys.argv[1], encoding="utf-8").read()
start = source.index("static PyObject *elisa_py_score")
end = source.index("static const char *elisa_pymodule_struct_names", start)
wrapper = source[start:end]
assert "native_result = elisa_pymodule_structs_score" in wrapper
assert "elisa_pymodule_struct_refs_free(&arg0_struct_refs);" in wrapper
assert "arena_free(&arg0_struct_arena);" in wrapper
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/structs.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_structs.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import gc
import sys

import structs

payload = {"kind": "point"}
point = {"x": 40, "small": -7, "y": 2.5, "ratio": 1.25, "label": "answer", "text": "α\x00β", "flag": True, "payload": payload}
assert structs.Point.__name__ == "Point"
assert structs.PointInput is structs.Point
assert structs.Point(x=40, small=-7, y=2.5, ratio=1.25, label="answer", text="α\x00β", flag=True, payload=payload) == point
assert "Point" in structs.__all__
assert structs.roundtrip(point) == point
assert structs.roundtrip(point)["payload"] is payload
assert structs.score(point) == 42.5
payload_refcount = sys.getrefcount(payload)
for _ in range(100):
    assert structs.score(point) == 42.5
assert sys.getrefcount(payload) == payload_refcount
assert structs.roundtrip({"x": -2, "small": 0, "y": 4.0, "ratio": 0.0, "label": "", "text": "", "flag": False, "payload": None})["x"] == -2

class Ephemeral:
    def __getattr__(self, name):
        # Return a fresh string with no caller-owned reference. The native call
        # must still see both text fields after field conversion finishes.
        values = {"x": 3, "small": 0, "y": 4.0, "ratio": 0.0, "label": "ephemeral-label", "text": "ephemeral-text", "flag": True, "payload": None}
        return "".join([values[name]]) if isinstance(values[name], str) else values[name]

ephemeral = structs.roundtrip(Ephemeral())
gc.collect()
assert ephemeral["label"] == "ephemeral-label"
assert ephemeral["text"] == "ephemeral-text"

for value in ({"x": 1}, {"x": 1, "small": 0, "y": 2.0, "ratio": 0.0, "label": "ok", "text": "", "flag": "yes", "payload": None}):
    try:
        structs.roundtrip(value)
    except (KeyError, TypeError) as exc:
        if "flag" in value:
            assert exc.path == ".flag"
            assert "at path .flag" in str(exc)
    else:
        raise AssertionError("invalid struct mapping accepted")

try:
    structs.roundtrip({"x": 1})
except KeyError as exc:
    assert "Elisa function 'roundtrip' argument 'point' at path .small:" in str(exc)
    assert exc.function == "roundtrip"
    assert exc.parameter == "point"
    assert exc.expected == "mapping or object"
    assert exc.path == ".small"
else:
    raise AssertionError("missing struct field should fail with parameter context")

try:
    structs.roundtrip({"x": 1, "small": 0, "y": 2.0, "ratio": 0.0, "label": "bad\x00label", "text": "", "flag": True, "payload": None})
except ValueError:
    pass
else:
    raise AssertionError("NUL-containing cstr struct field accepted")

try:
    structs.roundtrip({"x": 1, "small": 2147483648, "y": 2.0, "ratio": 0.0, "label": "ok", "text": "", "flag": True, "payload": None})
except OverflowError:
    pass
else:
    raise AssertionError("out-of-range narrow integer struct field accepted")

print("pymodule structs smoke OK")
PY
