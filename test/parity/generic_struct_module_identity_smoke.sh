#!/usr/bin/env bash
# Generic layouts and memoization follow template declarations, never basenames.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/bin/elisac-stage0}"
CLANG="${ELISA_CLANG:-clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-generic-owner.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

COMPILERS=("$STAGE1")
[[ ! -x "$STAGE0" ]] || COMPILERS+=("$STAGE0")
for compiler in "${COMPILERS[@]}"; do
    tag="$(basename -- "$compiler")"
for level in 0 2; do
    for repro in generic_struct_module_identity generic_struct_module_identity_reversed generic_struct_argument_owner generic_struct_relative_owner generic_struct_recursive_reference generic_struct_recursive_mutual_reference generic_struct_qualified_inference; do
        source="$ROOT/test/repro/$repro.elisa"
        "$compiler" -emit obj "-O$level" -o "$WORK/$tag-$repro-O$level.o" "$source"
        "$CLANG" -o "$WORK/$tag-$repro-O$level" "$WORK/$tag-$repro-O$level.o"
        set +e
        "$WORK/$tag-$repro-O$level"
        status=$?
        set -e
        [[ "$status" -eq 42 ]] || { echo "$repro -O$level returned $status, expected 42" >&2; exit 1; }
        "$compiler" -emit llvm "-O$level" -o "$WORK/$tag-$repro-O$level.ll" "$source"
    done
    negatives=(generic_struct_recursive_optional_layout generic_struct_recursive_array_layout)
    # Pinned Stage0 overflows its stack on mutual by-value recursion. Track that
    # upstream defect separately; Stage1 must report a bounded backend decline.
    [[ "$compiler" != "$STAGE1" ]] || negatives+=(generic_struct_recursive_mutual_layout)
    for repro in "${negatives[@]}"; do
        output="$WORK/$tag-$repro-O$level.ll"
        log="$WORK/$tag-$repro-O$level.log"
        if "$compiler" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/$repro.elisa" > "$log" 2>&1; then
            echo "generic owner smoke: accepted infinite $repro at -O$level" >&2
            exit 1
        fi
        [[ ! -e "$output" ]] || { echo "generic owner smoke: failed recursive layout left LLVM" >&2; exit 1; }
        rg -q 'recursi|declin|could not produce|circular' "$log" || { cat "$log" >&2; exit 1; }
        if [[ "$compiler" == "$STAGE1" && "$repro" != generic_struct_recursive_optional_layout ]]; then
            rg -q 'backend declined' "$log" || { cat "$log" >&2; exit 1; }
        fi
    done
done
done

# Runtime field accesses alone could pass even if both source types had the same wrong
# representation. Assert the declaration-specific LLVM field layouts independently.
tag="$(basename -- "$STAGE1")"
for repro in generic_struct_module_identity generic_struct_module_identity_reversed; do
    rg -q '^%Wrong\.Box__i64 = type \{ i64, i64 \}' "$WORK/$tag-$repro-O0.ll"
    rg -q '^%Right\.Box__i64 = type \{ i64 \}' "$WORK/$tag-$repro-O0.ll"
done
rg -q '^%Own\.Box__i64 = type \{ i32, i64 \}' "$WORK/$tag-generic_struct_argument_owner-O0.ll"
rg -q '^%Own\.Pair__i64__i32 = type \{ i64, i32 \}' "$WORK/$tag-generic_struct_argument_owner-O0.ll"
echo "generic struct module identity smoke OK: distinct layouts, argument owners, relative paths, inference, and recursive references at O0/O2"
