#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.14}"
PYTHON_CONFIG="${PYTHON_CONFIG:-/opt/homebrew/bin/python3.14-config}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
LLVM_NM="${ELISA_LLVM_NM:-/opt/homebrew/opt/llvm/bin/llvm-nm}"

if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" || ! -x "$CLANG" || ! -x "$LLVM_NM" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "pymodule constants smoke SKIP (Python/Homebrew clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/constants.json" \
    "$ROOT/test/repro/pymodule_constants.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/constants.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
assert manifest["module"] == "constants"
assert manifest["constants"] == [
    {"name": "level", "target": "API_LEVEL", "type": "i32"},
    {"name": "ratio", "target": "RATIO", "type": "f64"},
    {"name": "mask", "target": "MASK", "type": "u8"},
    {"name": "enabled", "target": "ENABLED", "type": "bool"},
    {"name": "inferred", "target": "INFERRED", "type": "int"},
    {"name": "count", "target": "counter", "type": "i64"},
]
PY

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/constants.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_constants.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import constants

assert constants.level == 7
assert constants.ratio == 0.25
assert constants.mask == 255
assert constants.enabled is True
assert constants.inferred == 9
assert constants.count == 3
assert constants.__all__ == ["level", "ratio", "mask", "enabled", "inferred", "count", "ElisaError"]
PY

# Darwin's bundle linker permits unresolved symbols, so the packaging audit must cover constant
# accessors as well as functions. Simulate a linker-visible object that lost one accessor and
# require the wrapper to report the exact exported symbol before producing an importable file.
NM_WRAPPER="$WORK/nm-missing-constant"
mkdir -p "$WORK/missing"
{
    printf '%s\n' '#!/usr/bin/env bash'
    printf '%q "$@" | grep -v "elisa_pymodule_constants_level"\n' "$LLVM_NM"
} >"$NM_WRAPPER"
chmod +x "$NM_WRAPPER"
if PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    ELISA_LLVM_NM="$NM_WRAPPER" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/missing/constants.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_constants.elisa" >"$WORK/missing.log" 2>&1; then
    echo "pymodule constant symbol audit accepted a missing accessor" >&2
    exit 1
fi
grep -Fq 'native pymodule symbol missing from object: elisa_pymodule_constants_level' "$WORK/missing.log"

echo "pymodule constants smoke OK"
