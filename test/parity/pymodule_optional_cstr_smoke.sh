#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional-cstr smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

SUFFIX="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_text$SUFFIX" \
    "$ROOT/test/repro/pymodule_optional_cstr.elisa" >/dev/null

cd "$WORK"
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import optional_text

assert optional_text.maybe() is None
assert optional_text.maybe(None) is None
assert optional_text.maybe("hello") == "hello"
assert optional_text.maybe(value="på") == "på"
assert optional_text.maybe(b"bytes") == "bytes"
for value in ("", b"", "på東京", "på東京".encode()):
    assert optional_text.maybe(value) == (value.decode() if isinstance(value, bytes) else value)
for value, error in ((b"\xff", UnicodeDecodeError), ("\ud800", UnicodeEncodeError),
                     (object(), TypeError), (bytearray(b"text"), TypeError)):
    try:
        optional_text.maybe(value)
    except error as exc:
        assert exc.parameter == "value"
    else:
        raise AssertionError("invalid nullable text accepted")
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
