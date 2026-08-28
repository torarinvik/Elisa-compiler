#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule qualified-targets smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/qualified_targets.json" \
    "$ROOT/test/repro/pymodule_qualified_targets.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/qualified_targets.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

assert manifest["module"] == "qualified_targets"
assert manifest["functions"][0]["name"] == "add"
assert manifest["functions"][0]["target"] == "Math::add"
assert manifest["functions"][0]["parameters"] == [
    {"name": "a", "type": "i64"},
    {"name": "b", "type": "i64"},
]
assert manifest["constants"] == [
    {"name": "version", "target": "Math::VERSION", "type": "i64"},
]
PY

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/missing.json" \
    "$ROOT/test/repro/pymodule_qualified_target_missing.elisa" >"$WORK/missing.out" 2>"$WORK/missing.err"; then
    echo "undefined qualified pymodule target should be rejected" >&2
    exit 1
fi
grep -Fq 'export target "Missing::add" is undefined' "$WORK/missing.err"

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/qualified_targets.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_qualified_targets.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import qualified_targets

assert qualified_targets.add(2, 5) == 7
assert qualified_targets.version == 7
assert qualified_targets.__all__ == ["add", "version", "ElisaError"]
PY

echo "pymodule qualified-targets smoke OK"
