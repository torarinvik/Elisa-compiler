#!/usr/bin/env bash
# Debug builder and file handles stay absent until initialized, and valid DWARF
# still reaches emitted objects when debug info is requested.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[ -x "$STAGE1" ] || { echo "debug_handle_initialization_smoke FAIL: no stage1 compiler at $STAGE1" >&2; exit 1; }
[ -x "$LLVM_CONFIG" ] || { echo "debug_handle_initialization_smoke SKIP: no llvm-config"; exit 0; }
DWARFDUMP="$("$LLVM_CONFIG" --bindir)/llvm-dwarfdump"
[ -x "$DWARFDUMP" ] || { echo "debug_handle_initialization_smoke SKIP: no llvm-dwarfdump"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/debug_probe.elisa" <<'EOF'
def helper(value: i64) -> i64:
    local: i64 = value + 1
    return local

def main() -> i64:
    return helper(41)
EOF

for level in O0 O2; do
    object="$WORK/debug-$level.o"
    dump="$WORK/debug-$level.dwarf"
    "$STAGE1" -emit obj -g "-$level" -o "$object" "$WORK/debug_probe.elisa"
    "$DWARFDUMP" --debug-info "$object" > "$dump"
    grep -q 'DW_TAG_compile_unit' "$dump"
    grep -q 'DW_TAG_subprogram' "$dump"
    if [ "$level" = O0 ]; then
        grep -q 'DW_TAG_formal_parameter' "$dump"
        grep -q 'DW_TAG_variable' "$dump"
    fi
done

echo "debug_handle_initialization_smoke OK: valid DWARF at O0/O2; parameter and local DIEs at O0"
