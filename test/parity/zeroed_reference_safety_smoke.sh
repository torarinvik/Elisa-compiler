#!/usr/bin/env bash
# Non-null references must never be materialized from a zero bit pattern.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/bin/elisac-stage0}"
CLANG="${ELISA_CLANG:-clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-zeroed-ref.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$STAGE1" ]] || { echo "zeroed reference smoke: missing Stage1: $STAGE1" >&2; exit 2; }
if [[ -x "$STAGE0" ]]; then
    bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
fi
command -v "$CLANG" >/dev/null 2>&1 || { echo "zeroed reference smoke: missing clang: $CLANG" >&2; exit 2; }

COMPILERS=("$STAGE1")
[[ -x "$STAGE0" ]] && COMPILERS+=("$STAGE0")

for repro in \
    zeroed_nonnull_reference.elisa \
    zeroed_nonnull_reference_alias.elisa \
    zeroed_nonnull_reference_global.elisa \
    zeroed_nonnull_reference_return.elisa \
    zeroed_generic_reference_return.elisa \
    zeroed_sview_return.elisa \
    zeroed_sview_field.elisa \
    zeroed_sview_trusted_field.elisa \
    uninitialized_nonnull_reference.elisa \
    zeroed_nonnull_reference_field.elisa \
    zeroed_nonnull_reference_array_field.elisa \
    zeroed_nonnull_reference_tuple.elisa \
    zeroed_nonnull_reference_nested_field.elisa \
    zeroed_nonnull_reference_generic_field.elisa; do
    for compiler in "${COMPILERS[@]}"; do
        for level in 0 2; do
            output="$WORK/$(basename -- "$compiler")-${repro%.elisa}-O$level.ll"
            log="$WORK/$(basename -- "$compiler")-${repro%.elisa}-O$level.log"
            if "$compiler" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/$repro" >"$log" 2>&1; then
                echo "zeroed reference smoke: $compiler accepted $repro at -O$level" >&2
                exit 1
            fi
            [[ ! -e "$output" ]] || {
                echo "zeroed reference smoke: failed compilation left an LLVM artifact for $repro" >&2
                exit 1
            }
            rg -q '(cannot initialize non-null reference .* from (zeroed|an omitted initializer)|cannot initialize aggregate .* from (zeroed|an omitted initializer): field .* requires a valid non-null value|cannot initialize .* from `zeroed`: .*non-null reference|use of uninitialized variable|(sview.*zeroed|zeroed.*sview))' "$log" || {
                echo "zeroed reference smoke: $compiler rejected $repro without the invalid-reference-initialization diagnostic" >&2
                cat "$log" >&2
                exit 1
            }
        done
    done
done

# Module-qualified aliases must resolve by their complete declaration identity. Keep this
# Stage1-only check until Stage0's equivalent alias resolver is qualified as well.
for level in 0 2; do
    output="$WORK/stage1-zeroed-qualified-reference-O$level.ll"
    log="$WORK/stage1-zeroed-qualified-reference-O$level.log"
    if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/zeroed_qualified_nonnull_reference_alias.elisa" >"$log" 2>&1; then
        echo "zeroed reference smoke: Stage1 accepted a module-qualified non-null reference alias at -O$level" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || {
        echo "zeroed reference smoke: failed qualified-alias compilation left an LLVM artifact" >&2
        exit 1
    }
    rg -q 'cannot initialize non-null reference .* from zeroed' "$log" || {
        echo "zeroed reference smoke: qualified-alias rejection used the wrong diagnostic" >&2
        cat "$log" >&2
        exit 1
    }
done

run_positive() {
    local compiler="$1" tag="$2" level="$3" source="$4"
    local name="$(basename -- "$source" .elisa)"
    local object="$WORK/$tag-$name-O$level.o" binary="$WORK/$tag-$name-O$level"
    "$compiler" -emit obj "-O$level" -o "$object" "$source"
    "$CLANG" -o "$binary" "$object"
    set +e
    "$binary"
    local result=$?
    set -e
    [[ "$result" -eq 42 ]] || {
        echo "zeroed reference smoke: $tag at -O$level returned $result, expected 42" >&2
        exit 1
    }
}

for level in 0 2; do
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/valid_initialized_reference.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_generic_scalar_field.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_generic_phantom_scalar.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_nested_generic_scalar.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_nullable_string_struct_array.elisa"
    if [[ -x "$STAGE0" ]]; then
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/valid_initialized_reference.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_generic_scalar_field.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_generic_phantom_scalar.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_nested_generic_scalar.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_nullable_string_struct_array.elisa"
    fi
done

for level in 0 2; do
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_qualified_nullable_reference_alias.elisa"
done

echo "zeroed reference smoke OK: invalid non-null references reject through locals, aliases, globals, qualified module aliases, generic and ordinary structs, named tuples, and fixed arrays; initialized references and nullable/scalar-generic storage return 42 at -O0/-O2"
