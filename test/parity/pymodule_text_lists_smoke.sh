#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule text-list smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/text_lists.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_text_lists.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import text_lists

assert text_lists.count(["one", "to", "three"]) == 3
assert text_lists.count([b"one", "to", b"three"]) == 3
assert text_lists.count(values=[]) == 0
assert text_lists.echo(["hello", "på", "東京"]) == ["hello", "på", "東京"]
assert text_lists.echo([b"hello", "på", b"\xce\xb1"]) == ["hello", "på", "α"]
assert text_lists.echo_cstr(["hello", "world"]) == ["hello", "world"]
assert text_lists.echo_cstr([b"hello", b"world"]) == ["hello", "world"]
try:
    text_lists.echo_cstr(["ok\x00bad"])
except ValueError:
    pass
else:
    raise AssertionError("cstr list should reject embedded NUL bytes")
try:
    text_lists.count([b"\xff"])
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("string list should reject invalid UTF-8 bytes")
PY

echo "pymodule text-list smoke OK"
