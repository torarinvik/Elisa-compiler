#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule optional-errors smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/optional_errors.json" +    "$ROOT/test/repro/pymodule_optional_errors.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/optional_errors.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert [(row["name"], row["return"]) for row in manifest["functions"]] == [
    ("value", "i64?"),
    ("flag", "bool?"),
    ("payload", "i64?"),
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/optional_errors.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_optional_errors.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import optional_errors

assert optional_errors.value(7) == 7
assert optional_errors.value(0) is None
assert optional_errors.flag(2) is True
assert optional_errors.flag(1) is False
assert optional_errors.flag(0) is None
assert optional_errors.payload(4) == 4
assert optional_errors.payload(0) is None

for function in (optional_errors.value, optional_errors.flag):
    try:
        function(-1)
    except optional_errors.ElisaError as exc:
        assert exc.code != 0
        assert exc.function in {"value", "flag"}
    else:
        raise AssertionError("negative optional-error input should raise ElisaError")

try:
    optional_errors.payload(-9)
except optional_errors.ElisaError as exc:
    assert exc.payload == -9
else:
    raise AssertionError("payload optional-error input should raise ElisaError")
PY

echo "pymodule optional-errors smoke OK"
