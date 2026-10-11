#!/usr/bin/env bash
# Stage in test/parity alongside fixture. Real 32/64-bit LLVM layouts run on the host.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
MODE="${ELISA_PACKED_WIDTH_COMPILER_MODE:-stage1}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-packed-width.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
# Never expand an empty array under macOS Bash 3 + nounset. Each mode installs at
# least one real link object before the common loop, and verifies all files.
case "$MODE" in
    stage1)
        COMPILER="${ELISA_STAGE1_BIN:?Pin the fresh candidate Stage1 compiler}"
        RUNTIME="${ELISA_RUNTIME_OBJ:?Pin its matching runtime object}"
        bash "$ROOT/scripts/assert_stage1_fresh.sh" "$COMPILER"
        [[ -f "$RUNTIME" ]] || { echo "missing candidate runtime: $RUNTIME" >&2; exit 2; }
        LINK_OBJECTS=("$RUNTIME")
        compile_control() {
            ELISA_STAGE1_BIN="$COMPILER" bash "$ROOT/scripts/elisac_stage1.sh" "$@"
        }
        ;;
    stage0)
        COMPILER="${ELISACORE_BIN:?Pin a fresh distinct Stage0 oracle}"
        bash "$ROOT/scripts/assert_stage0_fresh.sh" "$COMPILER"
        source "$ROOT/test/parity/native_optional_hook_objects.sh"
        elisa_native_optional_hook_objects "$WORK" "$ROOT"
        LINK_OBJECTS=("${ELISA_OPTIONAL_HOOK_OBJECTS[@]}")
        compile_control() { "$COMPILER" "$@"; }
        ;;
    *) echo "unknown compiler mode: $MODE (stage1 or stage0)" >&2; exit 2 ;;
esac
[[ "${#LINK_OBJECTS[@]}" -gt 0 ]] || { echo "missing link objects" >&2; exit 2; }
for link_object in "${LINK_OBJECTS[@]}"; do
    [[ -f "$link_object" ]] || { echo "missing link object: $link_object" >&2; exit 2; }
done
[[ -x "$CLANG" ]] || { echo "missing clang: $CLANG" >&2; exit 2; }
for opt in 0 2; do
    compile_control -O"$opt" -emit obj -o "$WORK/control-$opt.o" \
        "$ROOT/test/parity/packed_target_width_smoke.elisa" >"$WORK/compile-$opt.log" 2>&1 || {
        cat "$WORK/compile-$opt.log" >&2; exit 1;
    }
    "$CLANG" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS \
        "$WORK/control-$opt.o" "${LINK_OBJECTS[@]}" \
        -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS \
        -Wl,-rpath,"$ELISA_LLVM_LIBDIR" $ELISA_LD_STACK_512M -o "$WORK/control-$opt"
    "$WORK/control-$opt"
done
echo "packed target width OK ($MODE): real 32/64-bit layouts, absent-layout declines, O0/O2"
