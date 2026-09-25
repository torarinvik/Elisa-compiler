#!/usr/bin/env bash
# Non-null references must never be materialized from a zero bit pattern.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/bin/elisac}"
CLANG="${ELISA_CLANG:-clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-zeroed-ref.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$STAGE1" ]] || { echo "zeroed reference smoke: missing Stage1: $STAGE1" >&2; exit 2; }
command -v "$CLANG" >/dev/null 2>&1 || { echo "zeroed reference smoke: missing clang: $CLANG" >&2; exit 2; }

for repro in \
    zeroed_nonnull_reference.elisa \
    zeroed_nonnull_reference_alias.elisa \
    zeroed_nonnull_reference_global.elisa \
    uninitialized_nonnull_reference.elisa; do
    for level in 0 2; do
        output="$WORK/${repro%.elisa}-O$level.ll"
        log="$WORK/${repro%.elisa}-O$level.log"
        if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/$repro" >"$log" 2>&1; then
            echo "zeroed reference smoke: Stage1 accepted $repro at -O$level" >&2
            exit 1
        fi
        [[ ! -e "$output" ]] || {
            echo "zeroed reference smoke: failed compilation left an LLVM artifact for $repro" >&2
            exit 1
        }
        rg -q 'cannot initialize non-null reference .* from (zeroed|an omitted initializer)' "$log" || {
            echo "zeroed reference smoke: $repro failed without the invalid-reference-initialization diagnostic" >&2
            cat "$log" >&2
            exit 1
        }
    done
done

run_positive() {
    local compiler="$1" tag="$2" level="$3"
    local object="$WORK/$tag-O$level.o" binary="$WORK/$tag-O$level"
    "$compiler" -emit obj "-O$level" -o "$object" "$ROOT/test/repro/valid_initialized_reference.elisa"
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
    run_positive "$STAGE1" stage1 "$level"
    if [[ -x "$STAGE0" ]]; then
        run_positive "$STAGE0" stage0 "$level"
    fi
done

echo "zeroed reference smoke OK: zeroed or uninitialized non-null references reject; initialized and nullable references return 42 at -O0/-O2"
