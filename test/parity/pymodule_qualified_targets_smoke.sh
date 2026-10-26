#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/test/proofs/check_pymodule_target_owner_identity.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"

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

bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/target_owner_line_zero.json" \
    "$ROOT/test/repro/pymodule_target_owner_line_zero.elisa" >/dev/null
"$PYTHON_BIN" - "$WORK/target_owner_line_zero.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)

functions = {row["name"]: row["target"] for row in manifest["functions"]}
constants = {row["name"]: row["target"] for row in manifest["constants"]}
assert functions == {"first_fn": "Left::first", "second_fn": "Right::second"}, functions
assert constants == {"first_constant": "Left::FIRST", "second_constant": "Right::SECOND"}, constants
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

PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" ELISA_CLANG="$CLANG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/target_owner_line_zero.cpython-314-darwin.so" \
    "$ROOT/test/repro/pymodule_target_owner_line_zero.elisa" >/dev/null

PYTHONPATH="$WORK" "$PYTHON_BIN" - <<'PY'
import target_owner_line_zero

assert target_owner_line_zero.first_fn() == 11
assert target_owner_line_zero.second_fn() == 22
assert target_owner_line_zero.first_constant == 111
assert target_owner_line_zero.second_constant == 222
PY

echo "pymodule qualified-targets smoke OK"
