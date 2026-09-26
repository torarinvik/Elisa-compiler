#!/usr/bin/env bash
# Reference payloads must preserve nullability, pointer values, and blob extents.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
OPT="${ELISA_OPT:-/opt/homebrew/opt/llvm/bin/opt}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-enum-ref.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
compilers=("$STAGE1")
[[ ! -x "$STAGE0" ]] || compilers+=("$STAGE0")
for compiler in "${compilers[@]}"; do
    for level in 0 2; do
        for repro in zeroed_enum_nullable_payload enum_reference_payload_roundtrip; do
            "$compiler" -emit obj "-O$level" -o "$WORK/valid.o" "$ROOT/test/repro/$repro.elisa"
            "${ELISA_CLANG:-clang}" -fno-builtin -o "$WORK/valid" "$WORK/valid.o" "$RUNTIME" "$ROOT/scripts/pymodule_runtime_fallback.c" "$ROOT/test/parity/profile_hooks.c"
            set +e
            "$WORK/valid"
            status=$?
            set -e
            [[ "$status" == 42 ]] || { echo "$repro returned $status at O$level" >&2; exit 1; }
            "$compiler" -emit llvm "-O$level" -o "$WORK/valid.ll" "$ROOT/test/repro/$repro.elisa"
            "$OPT" -passes=verify -disable-output "$WORK/valid.ll"
        done
        output="$WORK/invalid.ll"
        if "$compiler" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/zeroed_enum_active_reference.elisa" > "$WORK/invalid.log" 2>&1; then
            echo 'accepted zeroed active non-null reference payload' >&2
            exit 1
        fi
        [[ ! -e "$output" ]] || { echo 'invalid reference payload left LLVM output' >&2; exit 1; }
        rg -q 'zeroed' "$WORK/invalid.log" || { cat "$WORK/invalid.log" >&2; exit 1; }
    done
    for level in 0 2; do
        "$compiler" -emit llvm "-O$level" -target-triple wasm32-unknown-wasi -o "$WORK/wasm.ll" "$ROOT/test/repro/enum_reference_payload_roundtrip.elisa"
        "$OPT" -passes=verify -disable-output "$WORK/wasm.ll"
        "${ELISA_WASM_CLANG:-/opt/homebrew/opt/llvm/bin/clang}" --target=wasm32-unknown-wasi -c "$WORK/wasm.ll" -o "$WORK/wasm.o"
        rg -q 'target datalayout = .*p:32:32' "$WORK/wasm.ll"
    done
done
"$STAGE1" -emit llvm -O0 -o "$WORK/layout.ll" "$ROOT/test/repro/enum_reference_payload_roundtrip.elisa"
rg -q '^define (internal )?i64 @nullable_score\(\{ i32, \[1 x i64\] \}' "$WORK/layout.ll"
rg -q '^define (internal )?i64 @direct_score\(\{ i32, \[1 x i64\] \}' "$WORK/layout.ll"
rg -q '^define (internal )?i64 @pair_score\(\{ i32, \[2 x i64\] \}' "$WORK/layout.ll"
echo 'enum reference payload smoke OK: null/direct/multi-field/alias/nested roundtrips at O0/O2; wasm32 LLVM verification and object emission'
