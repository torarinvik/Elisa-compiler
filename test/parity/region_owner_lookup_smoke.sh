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

if [[ -n "${ELISA_STAGE1_BIN:-}" ]]; then
    RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
    ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" bash "$ROOT/scripts/build_runtime_object.sh" >"$WORK/runtime.log" 2>&1 || {
        cat "$WORK/runtime.log" >&2
        echo "region owner lookup smoke FAIL: Stage1 runtime" >&2
        exit 1
    }
fi

[[ -x "$CLANG" ]] || { echo "region owner lookup smoke: missing clang: $CLANG" >&2; exit 2; }
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$WORK" "$ROOT"

# This harness includes the backend implementation directly to inspect the owner's
# retained-table facts. Use a supplied, provenance-checked Stage1 product when available;
# standalone invocations fall back to the configured Stage0 compiler.
compile_status=75
for attempt in {1..16}; do
    compile_status=0
    "$COMPILER" -emit obj -O0 -o "$WORK/region_owner_lookup.o" "$FIXTURE" >"$WORK/compile.log" 2>&1 || compile_status=$?
    [[ "$compile_status" -eq 75 ]] || break
    echo "region owner lookup: resuming Stage0 analysis checkpoint ($attempt/16)" >&2
done
if [[ "$compile_status" -ne 0 ]]; then
    cat "$WORK/compile.log" >&2
    echo "region owner lookup smoke FAIL: compile (status $compile_status)" >&2
    exit 1
fi
LINK_OBJECTS=("$WORK/region_owner_lookup.o")
if [[ -n "${ELISA_STAGE1_BIN:-}" ]]; then
    LINK_OBJECTS+=("$RUNTIME_OBJ")
fi
"$CLANG" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/region_owner_lookup" \
    "${LINK_OBJECTS[@]}" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" \
    -L"$LIBDIR" $ELISA_LLVM_LIBS $ELISA_LINK_EXE_FLAGS \
    -Wl,-rpath,"$LIBDIR" $ELISA_LD_STACK_512M
"$WORK/region_owner_lookup"

echo "region owner lookup smoke OK: qualified, aliased, and unresolved owner resolution"
