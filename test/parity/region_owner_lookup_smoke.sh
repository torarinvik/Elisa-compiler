#!/usr/bin/env bash
# Unit-level regression for qualified region-owner lookup and its owner-less fallback.
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
if [[ -n "${ELISA_STAGE1_BIN:-}" ]]; then
    COMPILER="$STAGE1"
    bash "$ROOT/scripts/assert_stage1_fresh.sh" "$COMPILER"
else
    COMPILER="$STAGE0"
    bash "$ROOT/scripts/assert_stage0_fresh.sh" "$COMPILER"
fi
FIXTURE="$ROOT/test/parity/region_owner_lookup_smoke.elisa"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
LIBDIR="$ELISA_LLVM_LIBDIR"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-region-owner.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$CLANG" ]] || { echo "region owner lookup smoke: missing clang: $CLANG" >&2; exit 2; }
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$WORK" "$ROOT"

# This harness includes the backend implementation directly to inspect the owner's
# retained-table facts. Use a supplied, provenance-checked Stage1 product when available;
# standalone invocations fall back to the configured Stage0 compiler.
"$COMPILER" -emit obj -O0 -o "$WORK/region_owner_lookup.o" "$FIXTURE" >"$WORK/compile.log" 2>&1 || {
    cat "$WORK/compile.log" >&2
    echo "region owner lookup smoke FAIL: compile" >&2
    exit 1
}
"$CLANG" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/region_owner_lookup" \
    "$WORK/region_owner_lookup.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" \
    -L"$LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS \
    -Wl,-rpath,"$LIBDIR" $ELISA_LD_STACK_512M
"$WORK/region_owner_lookup"

echo "region owner lookup smoke OK: qualified, aliased, and unresolved owner resolution"
