#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$(command -v clang || true)" ]]; then
    echo "pymodule struct-list-return smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_list_returns.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_list_returns.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_list_returns

value = struct_list_returns.make()
assert value == {
    "values": [4, -2],
    "weights": [1.5, 2.5],
    "flags": [True, False],
    "raw": b"A\x00B",
}
assert value["raw"] == b"A\x00B"
envelope = struct_list_returns.make_envelope()
assert envelope["name"] == "nested"
assert envelope["batch"] == value
print("pymodule struct-list-return smoke OK")
PY
