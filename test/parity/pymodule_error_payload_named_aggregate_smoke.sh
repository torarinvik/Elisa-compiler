#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule named-record aggregate error payload smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_error_payload_named_aggregate.elisa"

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/manifest.json" "$SOURCE" >/dev/null
python3 - "$WORK/manifest.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
functions = {row["name"]: row for row in manifest["functions"]}
assert functions["fail_list"]["payload"] == "darray[Point]"
assert functions["fail_view"]["payload"] == "view[Point]"
assert functions["fail_structured"]["payload"] == "struct"
assert functions["fail_structured"]["payload_variants"] == [{
    "name": "Bad",
    "fields": [
        {"name": "code", "type": "i64"},
        {"name": "points", "type": "darray[Point]"},
        {"name": "view_points", "type": "view[Point]"},
    ],
}]
PY

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi -o "$WORK/error_payload_named_aggregate.pyi" "$SOURCE" >/dev/null
grep -Fq 'def fail_list(points: Sequence[Point | PointInput]) -> int: ...' "$WORK/error_payload_named_aggregate.pyi"
grep -Fq 'def fail_view(points: Sequence[Point | PointInput]) -> int: ...' "$WORK/error_payload_named_aggregate.pyi"
grep -Fq 'def fail_structured(code: int, points: Sequence[Point | PointInput], view_points: Sequence[Point | PointInput]) -> int: ...' "$WORK/error_payload_named_aggregate.pyi"
grep -Fq 'class StructuredPointAggregatePayloadErrorBadPayload(TypedDict):' "$WORK/error_payload_named_aggregate.pyi"
grep -Fq 'StructuredPointAggregatePayloadErrorPayload = StructuredPointAggregatePayloadErrorBadPayload' "$WORK/error_payload_named_aggregate.pyi"
"$PYTHON_BIN" -m py_compile "$WORK/error_payload_named_aggregate.pyi"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/error_payload_named_aggregate.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import error_payload_named_aggregate as module

value = [{"x": 2, "label": "α\x00β"}, {"x": -1, "label": "done"}]
assert module.StructuredPointAggregatePayloadErrorBadPayload.__module__ == "error_payload_named_aggregate"
assert module.StructuredPointAggregatePayloadErrorPayload is module.StructuredPointAggregatePayloadErrorBadPayload
assert module.StructuredPointAggregatePayloadErrorBadPayload(
    variant="Bad", code=7, points=value, view_points=value
) == {"variant": "Bad", "code": 7, "points": value, "view_points": value}
try:
    module.fail_list(value)
except module.PointListPayloadError as exc:
    assert exc.payload == value
else:
    raise AssertionError("darray[Point] error payload should raise PointListPayloadError")

try:
    module.fail_view(value)
except module.PointViewPayloadError as exc:
    assert exc.payload == value
else:
    raise AssertionError("view[Point] error payload should raise PointViewPayloadError")

try:
    module.fail_structured(7, value, value)
except module.StructuredPointAggregatePayloadError as exc:
    assert exc.payload == {"variant": "Bad", "code": 7, "points": value, "view_points": value}
else:
    raise AssertionError("structured named-record aggregate payload should raise StructuredPointAggregatePayloadError")

for function, bad in (
    (module.fail_list, [{"x": "bad", "label": "ok"}]),
    (module.fail_view, [{"x": 1}]),
    (module.fail_structured, (7, [{"x": 1}], [])),
):
    try:
        function(*bad) if isinstance(bad, tuple) else function(bad)
    except (TypeError, KeyError):
        pass
    else:
        raise AssertionError((function.__name__, bad))

print("pymodule named-record aggregate error payload smoke OK")
PY
