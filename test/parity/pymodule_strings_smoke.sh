#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule strings smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/strings.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_strings.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import strings

assert strings.cstr("hello π") == "hello π"
assert strings.cstr(b"bytes") == "bytes"
assert strings.sview("a\x00bπ") == "a\x00bπ"
assert strings.sview(b"bytes") == "bytes"
assert strings.accept_cstr(b"bytes") == 1
assert strings.accept_sview(b"bytes") == 1
for function in (strings.cstr, strings.sview, strings.accept_cstr, strings.accept_sview):
    try:
        function(123)
    except TypeError as exc:
        assert exc.expected == "str | bytes"
    else:
        raise AssertionError("non-text scalar should be rejected")
try:
    strings.cstr("a\x00b")
except ValueError:
    pass
else:
    raise AssertionError("embedded NUL should be rejected for cstr")
try:
    strings.sview(b"\xff")
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 should fail")
try:
    strings.cstr(b"\xff")
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 cstr bytes should fail")
try:
    strings.accept_cstr(b"\xff")
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 cstr bytes should fail before native call")
try:
    strings.accept_sview(b"\xff")
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("invalid UTF-8 sview bytes should fail before native call")
PY

echo "pymodule strings smoke OK"
