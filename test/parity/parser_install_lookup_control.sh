#!/usr/bin/env bash
# Stage beside the fixture in test/parity. Strict real-parser unit, O0 and O2.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
RUNTIME_OBJECTS=()
if [[ -n "${ELISA_STAGE1_BIN:-}" ]]; then
    COMPILER="$ELISA_STAGE1_BIN"
    bash "$ROOT/scripts/assert_stage1_fresh.sh" "$COMPILER"
    RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
    ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" bash "$ROOT/scripts/build_runtime_object.sh" --check
    RUNTIME_OBJECTS=("$RUNTIME_OBJ")
else
    COMPILER="${ELISACORE_BIN:?Pin a fresh Stage0 oracle explicitly}"
    bash "$ROOT/scripts/assert_stage0_fresh.sh" "$COMPILER"
fi
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-install-lookup.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$WORK" "$ROOT"
for opt in 0 2; do
    "$COMPILER" -O"$opt" -emit obj -o "$WORK/control-$opt.o" \
        "$ROOT/test/parity/parser_install_lookup_control.elisa" >"$WORK/compile-$opt.log" 2>&1 || {
        cat "$WORK/compile-$opt.log" >&2; exit 1;
    }
    "$CLANG" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS \
        "$WORK/control-$opt.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" "${RUNTIME_OBJECTS[@]}" -o "$WORK/control-$opt" \
        $ELISA_LD_STACK_512M
    "$WORK/control-$opt"
done
echo "parser install lookup OK: missing/duplicate rows, ordered captures, scan fallback"
