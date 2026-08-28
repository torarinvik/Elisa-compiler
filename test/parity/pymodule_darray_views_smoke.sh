#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule darray views smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/darray_views.json" \
    "$ROOT/test/repro/pymodule_darray_views.elisa" >/dev/null

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/darray_views.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_darray_views.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import darray_views

assert darray_views.roundtrip_i64([[1, 2], [], [-3]]) == [[1, 2], [], [-3]]
assert darray_views.roundtrip_i64([(4, 5)]) == [[4, 5]]
assert darray_views.roundtrip_text([["a", "β"], [], [b"bytes"]]) == [["a", "β"], [], ["bytes"]]
assert darray_views.roundtrip_optional([[1, None, -2], []]) == [[1, None, -2], []]

marker = object()
result = darray_views.roundtrip_objects([[marker, None], []])
assert result[0][0] is marker
assert result[0][1] is None
assert result[1] == []

points = [[{"x": 1}, {"x": -2}], []]
assert darray_views.roundtrip_points(points) == points

for fn, value in (
    (darray_views.roundtrip_i64, [[1, 2**80]]),
    (darray_views.roundtrip_optional, [[2**80]]),
    (darray_views.roundtrip_text, [[None]]),
    (darray_views.roundtrip_points, [[{"x": "bad"}]]),
):
    try:
        fn(value)
    except (TypeError, OverflowError, ValueError):
        pass
    else:
        raise AssertionError("invalid darray view boundary accepted")

print("pymodule darray views smoke OK")
PY
