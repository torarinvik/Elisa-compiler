#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
LLC="${LLC:-$ELISA_LLVM_BIN_DIR/llc}"
[ -x "$LLC" ] || { echo "backend_trace_smoke SKIP: no llc"; exit 0; }

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

# Use the shipped driver to exercise the same backend trace path.
cat >"$BUILD/trace.elisa" <<'EOF'
def helper(x: i64) -> i64:
    y: i64 = x + 1
    return y

def main() -> i64:
    return helper(41)
EOF
"$STAGE1" -emit llvm -O0 -ftrace -o "$BUILD/trace.ll" "$BUILD/trace.elisa"
# Trace IDs are the current stable ABI: the legacy declarations remain for host
# compatibility, while emitted calls use the ID-carrying forms so a trace can be
# correlated across independently compiled units.
grep -Eq 'declare void @elisa_trace_record(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_record' "$BUILD/trace.ll"
grep -Eq 'declare void @elisa_trace_function_entry(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_function_entry' "$BUILD/trace.ll"
grep -Eq 'declare void @elisa_trace_function_exit(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_function_exit' "$BUILD/trace.ll"
grep -Eq 'declare void @elisa_trace_record_value(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_record_value' "$BUILD/trace.ll"
grep -q 'declare void @elisa_trace_install_fault_handler()' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_install_fault_handler()' "$BUILD/trace.ll"
"$LLC" -filetype=obj -o "$BUILD/trace.o" "$BUILD/trace.ll"
echo "backend trace smoke OK"
