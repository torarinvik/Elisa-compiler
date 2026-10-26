#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
python3 "$ROOT/test/proofs/check_backend_error_union_selected_row.py"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-extern-unsupported-ensure.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for fixture in \
    extern_unsupported_ensure_initializer.elisa \
    extern_unsupported_ensure_assignment.elisa \
    extern_unsupported_ensure_argument.elisa; do
    source="$ROOT/test/fixtures/backend/$fixture"
    stem="${fixture%.elisa}"
    elisa_run_timeout 29 "$ROOT/scripts/elisac_stage1.sh" -emit check "$source" >"$WORK/$stem-check.log" 2>&1 || {
        echo "unsupported extern-ensure control was not semantically accepted: $fixture" >&2
        sed -n '1,80p' "$WORK/$stem-check.log" >&2
        exit 1
    }
    for mode in llvm obj; do
        output="$WORK/$stem.$mode"
        invalid="$WORK/$stem.$mode.invalid.ll"
        status=0
        if elisa_run_timeout 29 env ELISA_DUMP_INVALID_IR="$invalid" \
            "$ROOT/scripts/elisac_stage1.sh" -emit "$mode" -o "$output" "$source" \
            >"$WORK/$stem-$mode.log" 2>&1; then
            status=0
        else
            status=$?
        fi
        [[ "$status" -eq 2 ]] || {
            echo "expected a clean backend decline for $fixture (-emit $mode), got status $status" >&2
            cat "$WORK/$stem-$mode.log" >&2
            exit 1
        }
        grep -Fq 'backend could not produce a linkable unit' "$WORK/$stem-$mode.log" || {
            echo "missing clean backend decline for $fixture (-emit $mode)" >&2
            cat "$WORK/$stem-$mode.log" >&2
            exit 1
        }
        grep -Fq 'old-value snapshot capture not found' "$WORK/$stem-$mode.log" || {
            echo "missing unsupported-predicate reason for $fixture (-emit $mode)" >&2
            cat "$WORK/$stem-$mode.log" >&2
            exit 1
        }
        if grep -Eq 'backend generated invalid LLVM IR|does not have terminator|unterminated basic block' "$WORK/$stem-$mode.log"; then
            echo "declined call left malformed LLVM for $fixture (-emit $mode)" >&2
            cat "$WORK/$stem-$mode.log" >&2
            exit 1
        fi
        [[ ! -e "$output" && ! -e "$invalid" ]] || {
            echo "failed compile wrote an object, LLVM file, or invalid-IR dump for $fixture (-emit $mode)" >&2
            ls -l "$output" "$invalid" 2>/dev/null || true
            exit 1
        }
    done
done

# Keep a valid selected-row ErrorUnion overload control alive at both optimizer levels.
# The result checks both the selected success payload and the selected failure-family tag.
control="$ROOT/test/fixtures/effects/helper_error_union_overload_capture.elisa"
for optimization in 0 2; do
    executable="$WORK/error-union-overload-O$optimization"
    elisa_run_timeout 29 "$ROOT/scripts/elisac_stage1.sh" -emit exe "-O$optimization" \
        -o "$executable" "$control" >"$WORK/error-union-overload-O$optimization.log" 2>&1 || {
        echo "supported ErrorUnion overload failed to compile at O$optimization" >&2
        sed -n '1,80p' "$WORK/error-union-overload-O$optimization.log" >&2
        exit 1
    }
    actual=0
    if elisa_run_timeout 10 "$executable"; then
        actual=0
    else
        actual=$?
    fi
    [[ "$actual" -eq 42 ]] || {
        echo "supported ErrorUnion overload returned $actual at O$optimization, expected 42" >&2
        exit 1
    }
done

# A generic template has no selected concrete row. Its descriptor fallback must
# still preserve both the success payload and the failure tag.
for optimization in 0 2; do
    executable="$WORK/generic-capture-O$optimization"
    elisa_run_timeout 29 "$STAGE1" -emit exe "-O$optimization" -o "$executable" \
        "$ROOT/test/fixtures/backend/selected_error_union_generic_capture.elisa" \
        >"$WORK/generic-capture-O$optimization.log" 2>&1 || {
        cat "$WORK/generic-capture-O$optimization.log" >&2
        echo "generic ErrorUnion capture failed to compile at O$optimization" >&2
        exit 1
    }
    if ! elisa_run_timeout 10 "$executable"; then
        echo "generic ErrorUnion capture failed at O$optimization" >&2
        exit 1
    fi
done

echo "unsupported extern-ensure declines cleanly; concrete and generic ErrorUnion controls pass at O0/O2"
