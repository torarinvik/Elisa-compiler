#!/usr/bin/env bash
# A named fallible call assigned into a record field must propagate its error before
# modifying the field and store the success payload on the success path.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
CLANG="${ELISA_CLANG:-$(dirname -- "$LLVM_CONFIG")/clang}"
SCALAR_FIXTURE="$ROOT/test/repro/try_field_assignment.elisa"
ENUM_FIXTURE="$ROOT/test/repro/try_qualified_enum_field_assignment.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-try-field-assignment.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$CLANG" ]] || { echo "try field assignment smoke: missing clang: $CLANG" >&2; exit 2; }
[[ -f "$RUNTIME_OBJ" ]] || { echo "try field assignment smoke: missing runtime object: $RUNTIME_OBJ" >&2; exit 2; }

bash "$ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$WORK/hooks.c"
LIBDIR="$("$LLVM_CONFIG" --libdir)"
run_case() {
    local stem="$1" fixture="$2" expected="$3"
    "$STAGE0" -emit obj -O0 -o "$WORK/$stem-stage0.o" "$fixture"
    "$CLANG" -Wl,-dead_strip -o "$WORK/$stem-stage0" "$WORK/$stem-stage0.o" "$RUNTIME_OBJ" \
        "$WORK/hooks.c" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" -Wl,-stack_size,0x20000000
    ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" \
        bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -o "$WORK/$stem-stage1" "$fixture"
    set +e
    "$WORK/$stem-stage0"
    local stage0_rc=$?
    "$WORK/$stem-stage1"
    local stage1_rc=$?
    set -e
    if [[ "$stage0_rc" -ne "$expected" || "$stage1_rc" -ne "$stage0_rc" ]]; then
        echo "try field assignment smoke FAILED ($stem): stage0=$stage0_rc stage1=$stage1_rc expected=$expected" >&2
        exit 1
    fi
}

run_case scalar "$SCALAR_FIXTURE" 123
run_case qualified_enum "$ENUM_FIXTURE" 42
echo "try field assignment smoke OK: scalar and qualified enum payloads store on success; failures preserve fields"
