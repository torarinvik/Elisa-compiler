#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule named-record error payload smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_error_payload_named_struct.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail_point"]["payload"] == "Point"
assert functions["fail_structured"]["payload"] == "struct"
assert functions["fail_structured"]["payload_variants"] == [{
    "name": "Bad",
    "fields": [
        {"name": "code", "type": "i64"},
        {"name": "point", "type": "Point"},
    ],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/error_payload_named_struct.pyi" "$SOURCE" >/dev/null
grep -Fq 'def fail_point(point: Point | PointInput) -> int: ...' "$WORK/error_payload_named_struct.pyi"
grep -Fq 'def fail_structured(code: int, point: Point | PointInput) -> int: ...' "$WORK/error_payload_named_struct.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_named_struct.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_named_struct.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_named_struct as module

point = {"x": 2, "label": "α\x00β"}
try:
    module.fail_point(point)
except module.PointPayloadError as exc:
    assert exc.payload == point
else:
    raise AssertionError("named-record error payload should raise PointPayloadError")

try:
    module.fail_structured(7, point)
except module.StructuredPointPayloadError as exc:
    assert exc.payload == {"variant": "Bad", "code": 7, "point": point}
else:
    raise AssertionError("structured named-record error payload should raise StructuredPointPayloadError")

for function, bad in ((module.fail_point, {"x": "bad", "label": "ok"}), (module.fail_structured, (7, {"x": 1}))):
    try:
        function(*bad) if isinstance(bad, tuple) else function(bad)
    except (TypeError, KeyError):
        pass
    else:
        raise AssertionError((function.__name__, bad))

print("pymodule named-record error payload smoke OK")
PY
