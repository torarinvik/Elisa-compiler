#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule wildcard smoke SKIP (Python 3.14/Homebrew clang/runtime unavailable)"
    exit 0
fi

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/wildcard.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_wildcard.elisa" >/dev/null

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/wildcard.json" "$ROOT/test/repro/pymodule_wildcard.elisa" >/dev/null

PYTHON_BIN="$PYTHON_BIN" bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/wildcard.pyi" "$ROOT/test/repro/pymodule_wildcard.elisa" >/dev/null

grep -Fq '"name": "add"' "$WORK/wildcard.json"
grep -Fq '"name": "greet"' "$WORK/wildcard.json"
grep -Fq '"name": "API_LEVEL"' "$WORK/wildcard.json"
grep -Fq 'def add(a: int, b: int) -> int: ...' "$WORK/wildcard.pyi"
grep -Fq 'def greet(name: str | bytes) -> str: ...' "$WORK/wildcard.pyi"
grep -Fq 'API_LEVEL: Final[int]' "$WORK/wildcard.pyi"

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import wildcard

assert wildcard.add(2, 4) == 6
assert wildcard.greet(b"hello") == "hello"
assert wildcard.API_LEVEL == 3
assert wildcard.__all__ == ["add", "greet", "API_LEVEL", "ElisaError"]
PY

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/duplicate.c" "$ROOT/test/repro/pymodule_wildcard_duplicate.elisa" >"$WORK/duplicate.log" 2>&1; then
    echo "wildcard plus explicit duplicate should be rejected" >&2
    exit 1
fi
grep -Fq 'duplicate Python module export name "add": public module names must be unique' "$WORK/duplicate.log"

echo "pymodule wildcard smoke OK"
