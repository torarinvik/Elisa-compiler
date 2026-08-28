#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$(command -v clang || true)" ]]; then
    echo "pymodule struct-text-list smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_text_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_text_lists.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_text_lists

assert struct_text_lists.count({"names": ["one", "på"], "labels": ["A", "B"]}) == 4
assert struct_text_lists.count({"names": [b"one", b"p\xc3\xa5"], "labels": [b"A", b"B"]}) == 4
assert struct_text_lists.make(["hello", "東京"], ["x", "y"]) == {
    "names": ["hello", "東京"],
    "labels": ["x", "y"],
}
try:
    struct_text_lists.count({"names": [], "labels": ["ok\x00bad"]})
except ValueError:
    pass
else:
    raise AssertionError("struct cstr list should reject embedded NUL bytes")
print("pymodule struct-text-list smoke OK")
PY
