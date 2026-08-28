#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional-cstr smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_text.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_optional_cstr.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import optional_text

assert optional_text.maybe() is None
assert optional_text.maybe(None) is None
assert optional_text.maybe("hello") == "hello"
assert optional_text.maybe(value="på") == "på"
assert optional_text.maybe(b"bytes") == "bytes"
assert str(inspect.signature(optional_text.maybe)) == "(value=None)"
try:
    optional_text.maybe("a\x00b")
except ValueError:
    pass
else:
    raise AssertionError("embedded NUL should be rejected for cstr?")
try:
    optional_text.maybe(b"a\x00b")
except ValueError:
    pass
else:
    raise AssertionError("embedded NUL bytes should be rejected for cstr?")
PY

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/nontrailing.c" \
    "$ROOT/test/repro/pymodule_optional_nontrailing.elisa" >"$WORK/nontrailing.log" 2>&1; then
    echo "non-trailing nullable parameter should be rejected by pymodule-c" >&2
    exit 1
fi
grep -Fq "default/nullable parameters to be trailing" "$WORK/nontrailing.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/nontrailing.json" \
    "$ROOT/test/repro/pymodule_optional_nontrailing.elisa" >"$WORK/nontrailing_manifest.log" 2>&1; then
    echo "non-trailing nullable parameter should be rejected by the pymodule manifest" >&2
    exit 1
fi
grep -Fq "default/nullable parameters to be trailing" "$WORK/nontrailing_manifest.log"

echo "pymodule optional-cstr smoke OK"
