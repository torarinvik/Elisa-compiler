#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
export PYTHON_BIN PYTHON_CONFIG
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$(command -v clang || true)" ]]; then
    echo "pymodule struct-object-input smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/struct_object_input.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_struct_object_input.elisa" >/dev/null
PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import struct_object_input
import sys

first = {"kind": "mapping"}
second = [1, 2, 3]
assert struct_object_input.count({"values": [first, second, None]}) == 3
assert struct_object_input.count(type("Batch", (), {"values": (first, second)})()) == 2
first_refcount = sys.getrefcount(first)
for _ in range(100):
    assert struct_object_input.count({"values": [first]}) == 1
assert sys.getrefcount(first) == first_refcount

class EphemeralSequence:
    def __init__(self):
        self.items = [{"ephemeral": True}, object()]
    def __len__(self):
        return len(self.items)
    def __getitem__(self, index):
        if index >= len(self.items):
            raise IndexError
        return self.items[index]

batch = EphemeralSequence()
echoed = struct_object_input.echo({"values": batch})
assert echoed["values"] == batch.items
nullable = struct_object_input.nullable_echo({"values": [None, first, None]})
assert nullable["values"] == [None, first, None]
print("pymodule struct-object-input smoke OK")
PY
