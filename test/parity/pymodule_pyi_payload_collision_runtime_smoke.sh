#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule payload collision runtime smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/pymodule_pyi_payload_collision.elisa"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/pyi_payload_collision.cpython-314-darwin.so" "$SOURCE" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import pyi_payload_collision as module

# Struct aliases occupy the preferred names; payload factories must follow the
# same deterministic suffixing policy as the generated .pyi.
assert module.CollisionBadPayload.__module__ == "pyi_payload_collision"
assert module.CollisionPayload.__module__ == "pyi_payload_collision"
assert module.CollisionBadPayload_1.__module__ == "pyi_payload_collision"
assert module.CollisionPayload_1 is module.CollisionBadPayload_1
assert module.CollisionBadPayload_1(variant="Bad", code=1, detail=2) == {
    "variant": "Bad", "code": 1, "detail": 2
}
print("pymodule payload collision runtime smoke OK")
PY
