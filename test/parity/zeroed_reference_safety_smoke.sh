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

# A borrowed view must not acquire a zero representation through a qualified alias.
# Stage0's matching alias resolver has not been qualified yet, so this regression runs on
# Stage1 until that separate compiler-generation gap is closed.
for level in 0 2; do
    output="$WORK/stage1-zeroed-qualified-sview-O$level.ll"
    log="$WORK/stage1-zeroed-qualified-sview-O$level.log"
    if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/zeroed_qualified_sview_alias.elisa" >"$log" 2>&1; then
        echo "zeroed reference smoke: Stage1 accepted a module-qualified sview alias at -O$level" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || {
        echo "zeroed reference smoke: failed qualified-sview compilation left an LLVM artifact" >&2
        exit 1
    }
    rg -q 'sview with valid backing' "$log" || {
        echo "zeroed reference smoke: qualified-sview rejection used the wrong diagnostic" >&2
        cat "$log" >&2
        exit 1
    }
done

# A qualified handle alias is an invalid zero representation only when it is non-null.
# The non-null value must remain uninitialized until assigned; an optional handle's zero
# representation is valid and remains an accepted executable control.
for level in 0 2; do
    output="$WORK/stage1-zeroed-qualified-handle-O$level.ll"
    log="$WORK/stage1-zeroed-qualified-handle-O$level.log"
    if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/zeroed_qualified_handle_alias.elisa" >"$log" 2>&1; then
        echo "zeroed reference smoke: Stage1 accepted a returned module-qualified zeroed handle at -O$level" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || {
        echo "zeroed reference smoke: failed qualified-handle compilation left an LLVM artifact" >&2
        exit 1
    }
    rg -q 'use of uninitialized variable' "$log" || {
        echo "zeroed reference smoke: qualified-handle rejection used the wrong diagnostic" >&2
        cat "$log" >&2
        exit 1
    }
done

# Nested-module checks must resolve aliases against the file declaration tree while
# retaining the current module's narrower struct-field lookup context.
for level in 0 2; do
    for repro in zeroed_nested_module_sview_alias.elisa zeroed_nested_module_handle_alias.elisa zeroed_nested_module_reference_alias.elisa; do
        output="$WORK/stage1-$repro-O$level.ll"
        log="$WORK/stage1-$repro-O$level.log"
        if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/$repro" >"$log" 2>&1; then
            echo "zeroed reference smoke: Stage1 accepted $repro at -O$level" >&2
            exit 1
        fi
        [[ ! -e "$output" ]] || {
            echo "zeroed reference smoke: failed nested-module compilation left an LLVM artifact for $repro" >&2
            exit 1
        }
        expected='sview with valid backing'
        if [[ "$repro" == zeroed_nested_module_handle_alias.elisa ]]; then
            expected='use of uninitialized variable'
        fi
        if [[ "$repro" == zeroed_nested_module_reference_alias.elisa ]]; then
            expected='cannot initialize non-null reference .* from zeroed'
        fi
        rg -q "$expected" "$log" || {
            echo "zeroed reference smoke: nested-module rejection used the wrong diagnostic for $repro" >&2
            cat "$log" >&2
            exit 1
        }
    done
done

# An `extend Module:` block is a second AST module fragment with the same owner. Its aliases
# share that module's namespace and can chain to aliases declared in the original fragment.
# This Stage1-only regression covers all three invalid-zero classifiers; the pinned Stage0
# currently reports these qualified aliases as unknown types.
for level in 0 2; do
    output="$WORK/stage1-zeroed-extended-module-alias-O$level.ll"
    log="$WORK/stage1-zeroed-extended-module-alias-O$level.log"
    if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/zeroed_extended_module_alias_chain.elisa" >"$log" 2>&1; then
        echo "zeroed reference smoke: Stage1 accepted invalid aliases split across a module extension at -O$level" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || {
        echo "zeroed reference smoke: failed extended-module compilation left an LLVM artifact at -O$level" >&2
        exit 1
    }
    rg -q 'sview with valid backing' "$log" || {
        echo "zeroed reference smoke: extended-module sview alias used the wrong diagnostic" >&2
        cat "$log" >&2
        exit 1
    }
    rg -q 'variable "nested_view" expects sview with valid backing' "$log" || {
        echo "zeroed reference smoke: relative alias target was not resolved from its declaring module owner" >&2
        cat "$log" >&2
        exit 1
    }
    rg -q 'cannot initialize non-null reference .* from zeroed' "$log" || {
        echo "zeroed reference smoke: extended-module reference alias used the wrong diagnostic" >&2
        cat "$log" >&2
        exit 1
    }
    rg -q 'use of uninitialized variable' "$log" || {
        echo "zeroed reference smoke: extended-module handle alias used the wrong diagnostic" >&2
        cat "$log" >&2
        exit 1
    }
done

# Relative lookup must honor the closest module that defines the requested alias. A
# same-named outer alias must not make an inner scalar alias look like a borrowed view, and
# a nearer borrowed-view alias must not be skipped in favor of an enclosing scalar alias.
# The scalar shadow currently reaches a known Stage1 backend-decline path; accept either that
# conservative decline (without an sview safety diagnostic) or successful future lowering.
for level in 0 2; do
    output="$WORK/stage1-zeroed-nearest-scalar-O$level.ll"
    log="$WORK/stage1-zeroed-nearest-scalar-O$level.log"
    if ! "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/zeroed_relative_shadow_nearest_scalar.elisa" >"$log" 2>&1; then
        [[ ! -e "$output" ]] || {
            echo "zeroed reference smoke: backend decline left a nearest-scalar LLVM artifact at -O$level" >&2
            exit 1
        }
        if rg -q 'sview with valid backing' "$log"; then
            echo "zeroed reference smoke: outer borrowed-view alias shadowed the nearest scalar alias at -O$level" >&2
            cat "$log" >&2
            exit 1
        fi
        rg -q 'backend declined .*variable declaration' "$log" || {
            echo "zeroed reference smoke: nearest-scalar control failed outside the known backend-decline path" >&2
            cat "$log" >&2
            exit 1
        }
    fi

    output="$WORK/stage1-zeroed-nearest-sview-O$level.ll"
    log="$WORK/stage1-zeroed-nearest-sview-O$level.log"
    if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/zeroed_relative_shadow_nearest_sview.elisa" >"$log" 2>&1; then
        echo "zeroed reference smoke: Stage1 skipped the nearest borrowed-view alias at -O$level" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || {
        echo "zeroed reference smoke: nearest-sview rejection left an LLVM artifact at -O$level" >&2
        exit 1
    }
    rg -q 'sview with valid backing' "$log" || {
        echo "zeroed reference smoke: nearest borrowed-view alias used the wrong diagnostic" >&2
        cat "$log" >&2
        exit 1
    }
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

# A module path may be written relative to the current module or any enclosing module.
# Exercise every classifier through those language-supported spellings; exact fully
# qualified paths are covered above. These checks stay Stage1-only until Stage0 implements
# the same declaration-owner lookup.
for level in 0 2; do
    for repro in \
        zeroed_relative_nested_module_sview_alias.elisa \
        zeroed_relative_sibling_module_sview_alias.elisa \
        zeroed_relative_nested_module_reference_alias.elisa \
        zeroed_relative_sibling_module_handle_alias.elisa; do
        output="$WORK/stage1-$repro-O$level.ll"
        log="$WORK/stage1-$repro-O$level.log"
        if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/$repro" >"$log" 2>&1; then
            echo "zeroed reference smoke: Stage1 accepted relative module alias $repro at -O$level" >&2
            exit 1
        fi
        [[ ! -e "$output" ]] || {
            echo "zeroed reference smoke: failed relative-alias compilation left an LLVM artifact for $repro" >&2
            exit 1
        }
        expected='sview with valid backing'
        if [[ "$repro" == zeroed_relative_nested_module_reference_alias.elisa ]]; then
            expected='cannot initialize non-null reference .* from zeroed'
        elif [[ "$repro" == zeroed_relative_sibling_module_handle_alias.elisa ]]; then
            expected='use of uninitialized variable'
        fi
        rg -q "$expected" "$log" || {
            echo "zeroed reference smoke: relative-alias rejection used the wrong diagnostic for $repro" >&2
            cat "$log" >&2
            exit 1
        }
    done
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
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_nullable_reference_aggregate.elisa"
    if [[ -x "$STAGE0" ]]; then
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/valid_initialized_reference.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_generic_scalar_field.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_generic_phantom_scalar.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_nested_generic_scalar.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_nullable_string_struct_array.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_nullable_reference_aggregate.elisa"
    fi
done

for level in 0 2; do
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_qualified_nullable_reference_alias.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_qualified_nullable_handle_alias.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_qualified_nullable_sview_alias.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_nested_module_nullable_sview_alias.elisa"
    run_positive "$STAGE1" stage1 "$level" "$ROOT/test/repro/zeroed_relative_nullable_sview_alias.elisa"
    if [[ -x "$STAGE0" ]]; then
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_qualified_nullable_reference_alias.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_qualified_nullable_handle_alias.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_qualified_nullable_sview_alias.elisa"
        run_positive "$STAGE0" stage0 "$level" "$ROOT/test/repro/zeroed_nested_module_nullable_sview_alias.elisa"
    fi
done

echo "zeroed reference smoke OK: invalid non-null references reject across direct, aliased, aggregate, and generic storage; qualified non-null handles and borrowed views reject; nullable references, handles, views, and reference-bearing aggregates return 42 at -O0/-O2"
