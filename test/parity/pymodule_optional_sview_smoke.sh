#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional-sview smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/optional_sview.json" \
    "$ROOT/test/repro/pymodule_optional_sview_probe.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/optional_sview.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
row = manifest["functions"][0]
assert row["parameters"] == [{"name": "value", "type": "sview?", "default": "None"}]
assert row["return"] == "sview?"
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_sview_probe.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_optional_sview_probe.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import inspect
import optional_sview_probe

assert optional_sview_probe.maybe_text() is None
assert optional_sview_probe.maybe_text(None) is None
value = "hello\x00på\x00東京"
assert optional_sview_probe.maybe_text(value) == value
assert optional_sview_probe.maybe_text(b"bytes\x00ok") == "bytes\x00ok"
assert str(inspect.signature(optional_sview_probe.maybe_text)) == "(value=None)"
try:
    optional_sview_probe.maybe_text(b"\xff")
except UnicodeDecodeError:
    pass
else:
    raise AssertionError("optional sview should reject invalid UTF-8 bytes")
PY

echo "pymodule optional-sview smoke OK"
