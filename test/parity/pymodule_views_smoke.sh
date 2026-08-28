#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule views smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/views.json" \
    "$ROOT/test/repro/pymodule_views.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/views.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    rows = {row["name"]: row for row in json.load(handle)["functions"]}
assert rows["count_i64"]["parameters"] == [{"name": "values", "type": "view[i64]"}]
assert rows["first_i64"]["return"] == "i64"
assert rows["identity_i64"]["return"] == "view[i64]"
assert rows["sum_u16"]["return"] == "u64"
assert rows["count_text"]["parameters"] == [{"name": "values", "type": "view[sview]"}]
assert rows["count_objects"]["parameters"] == [{"name": "values", "type": "view[py::Object]"}]
assert rows["count_nullable"]["parameters"] == [{"name": "values", "type": "view[i64?]"}]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/views.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_views.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import views

assert views.count_i64([1, 2, 3]) == 3
assert views.count_i64((4, 5)) == 2
assert views.first_i64([9, 8]) == 9
assert views.identity_i64([1, 2, 3]) == [1, 2, 3]
assert views.identity_i64(()) == []
assert views.identity_u8(b"abc") == b"abc"
assert views.identity_u8(memoryview(b"xyz")) == b"xyz"
assert views.sum_u16([1, 65535, 4]) == 65540
assert views.count_i64([]) == 0
assert views.count_text(["a", "β", "c"]) == 3
assert views.count_text([b"a", b"\xce\xb2", b"c"]) == 3
assert views.count_objects([object(), {"x": 1}, None]) == 3
assert views.count_nullable([1, None, -2]) == 3

for fn, value in ((views.sum_u16, [1, -1]), (views.sum_u16, [1, 65536])):
    try:
        fn(value)
    except (TypeError, IndexError, OverflowError):
        pass
    else:
        raise AssertionError("invalid view boundary accepted")
try:
    views.count_text([b"\xff"])
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 view text accepted")
PY

echo "pymodule views smoke OK"
