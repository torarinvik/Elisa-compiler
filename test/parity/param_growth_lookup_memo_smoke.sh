#!/usr/bin/env bash
# Stage beside the fixture in test/parity. Exercise exact cached lookup results at O0/O2.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
if [[ -n "${ELISA_STAGE1_BIN:-}" ]]; then
    COMPILER="$ELISA_STAGE1_BIN"
    bash "$ROOT/scripts/assert_stage1_fresh.sh" "$COMPILER"
    RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
    ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" bash "$ROOT/scripts/build_runtime_object.sh" --check
else
    COMPILER="${ELISACORE_BIN:?Pin a fresh Stage0 oracle explicitly}"
    bash "$ROOT/scripts/assert_stage0_fresh.sh" "$COMPILER"
fi
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-pgs-memo.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$WORK" "$ROOT"
LINK_OBJECTS=("${ELISA_OPTIONAL_HOOK_OBJECTS[@]}")
if [[ -n "${ELISA_STAGE1_BIN:-}" ]]; then
    LINK_OBJECTS+=("$RUNTIME_OBJ")
fi
for opt in 0 2; do
    "$COMPILER" -O"$opt" -emit obj -o "$WORK/control-$opt.o" \
        "$ROOT/test/parity/param_growth_lookup_memo_control.elisa" >"$WORK/compile-$opt.log" 2>&1 || {
        cat "$WORK/compile-$opt.log" >&2; exit 1;
    }
    "$CLANG" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS \
        "$WORK/control-$opt.o" "${LINK_OBJECTS[@]}" \
        -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS \
        -Wl,-rpath,"$ELISA_LLVM_LIBDIR" $ELISA_LD_STACK_512M -o "$WORK/control-$opt"
    "$WORK/control-$opt"
done
echo "parameter-growth memo control OK at O0/O2: full accumulator result, exact keys, cached misses"
