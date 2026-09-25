#!/usr/bin/env bash
# Target-machine FFI smoke: nullable LLVM handles must use the C pointer ABI at every
# boundary, and invalid triples must fail before a null target reaches LLVM.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[ -x "$STAGE1" ] || { echo "target_machine_ffi FAIL: no stage1 compiler at $STAGE1" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cat >"$WORK/probe.elisa" <<'EOF'
def main() -> i64:
    return 42
EOF

# Default native target: exercise target lookup, target-machine creation, data-layout
# installation, object emission, final linking, and the resulting program.
"$STAGE1" -emit exe -O0 -o "$WORK/default" "$WORK/probe.elisa"
set +e
"$WORK/default"
run_status=$?
set -e
if [ "$run_status" -ne 42 ]; then
    echo "target_machine_ffi FAIL: default-target program returned $run_status, want 42" >&2
    exit 1
fi

# An explicitly selected, initialized LLVM target exercises the non-native lookup path.
"$STAGE1" -target-triple x86_64-unknown-linux-gnu -emit obj -O2 \
    -o "$WORK/x86_64.o" "$WORK/probe.elisa"
[ -s "$WORK/x86_64.o" ] || { echo "target_machine_ffi FAIL: explicit-target object is empty" >&2; exit 1; }

# LLVM returns an error status and optional error message for an unknown triple. The
# compiler must report that failure instead of passing a null target into target creation.
if "$STAGE1" -target-triple not-a-real-target-0-none -emit obj \
    -o "$WORK/invalid.o" "$WORK/probe.elisa" >"$WORK/invalid.log" 2>&1; then
    echo "target_machine_ffi FAIL: invalid triple unexpectedly compiled" >&2
    exit 1
else
    invalid_status=$?
fi
if [ "$invalid_status" -eq 139 ] || ! grep -Fq \
    "LLVM could not resolve the requested target triple" "$WORK/invalid.log"; then
    cat "$WORK/invalid.log" >&2
    echo "target_machine_ffi FAIL: invalid triple did not take the checked error path (status $invalid_status)" >&2
    exit 1
fi

echo "target_machine_ffi OK: native O0 execution, explicit x86_64 O2 emission, checked invalid-triple failure"
