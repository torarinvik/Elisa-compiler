#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule bytes smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/bytesprobe.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_bytes_probe.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import bytesprobe

assert bytesprobe.count(b"abc\x00xyz") == 7
assert bytesprobe.echo(b"abc\x00xyz") == b"abc\x00xyz"
assert bytesprobe.echo(b"") == b""
assert bytesprobe.count(bytearray(b"mutable")) == 7
assert bytesprobe.echo(bytearray(b"mutable")) == b"mutable"
assert bytesprobe.echo(memoryview(b"view")) == b"view"
assert bytesprobe.pair_count(bytearray(b"left"), memoryview(b"right")) == 9
try:
    bytesprobe.count("abc")
except TypeError:
    pass
else:
    raise AssertionError("darray[u8] should require bytes")
PY

echo "pymodule bytes smoke OK"
