#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "region-pool release lifetime smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

BAD="$ROOT/test/repro/region_pool_primitive_after_release.elisa"
CONDITION_BAD="$ROOT/test/repro/region_pool_primitive_after_condition_release.elisa"
NESTED_FIELD_BAD="$ROOT/test/repro/region_pool_nested_field_after_release.elisa"
GOOD="$ROOT/test/parity/fixtures/region_pool_primitive_before_release.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-region-pool-release.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

for optimization in 0 2; do
    bad_output="$WORK/after-release-O$optimization.ll"
    bad_log="$bad_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$bad_output" "$BAD" >"$bad_log" 2>&1; then
        echo "region-pool release lifetime smoke: accepted a copied pointer after pool.release at -O$optimization" >&2
        exit 1
    fi
    rg -Fq 'interior reference "ptr" cannot be used: usage facts were consumed by argument to call "release"' "$bad_log" || {
        echo "region-pool release lifetime smoke: missing precise release invalidation diagnostic at -O$optimization" >&2
        cat "$bad_log" >&2
        exit 1
    }
    [[ ! -e "$bad_output" ]] || { echo "region-pool release lifetime smoke: wrote LLVM for a rejected stale pointer at -O$optimization" >&2; exit 1; }

    condition_output="$WORK/condition-release-O$optimization.ll"
    condition_log="$condition_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$condition_output" "$CONDITION_BAD" >"$condition_log" 2>&1; then
        echo "region-pool release lifetime smoke: accepted a copied pointer after a consuming call in an if condition at -O$optimization" >&2
        exit 1
    fi
    rg -Fq 'interior reference "ptr" cannot be used: usage facts were consumed by argument to call "release_and_false"' "$condition_log" || {
        echo "region-pool release lifetime smoke: missing condition-call invalidation diagnostic at -O$optimization" >&2
        cat "$condition_log" >&2
        exit 1
    }
    [[ ! -e "$condition_output" ]] || { echo "region-pool release lifetime smoke: wrote LLVM for a rejected condition-stale pointer at -O$optimization" >&2; exit 1; }

    nested_field_output="$WORK/nested-field-after-release-O$optimization.ll"
    nested_field_log="$nested_field_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$nested_field_output" "$NESTED_FIELD_BAD" >"$nested_field_log" 2>&1; then
        echo "region-pool release lifetime smoke: accepted a pointer borrowed through handle.ptr.value after release at -O$optimization" >&2
        exit 1
    fi
    rg -Fq 'interior reference "ptr" cannot be used: usage facts were consumed by argument to call "release"' "$nested_field_log" || {
        echo "region-pool release lifetime smoke: missing nested-field release invalidation diagnostic at -O$optimization" >&2
        cat "$nested_field_log" >&2
        exit 1
    }
    [[ ! -e "$nested_field_output" ]] || { echo "region-pool release lifetime smoke: wrote LLVM for a rejected nested-field stale pointer at -O$optimization" >&2; exit 1; }

    good_output="$WORK/before-release-O$optimization.ll"
    "$STAGE1" -emit llvm "-O$optimization" -o "$good_output" "$GOOD" >"$WORK/before-release-O$optimization.log" 2>&1 || {
        echo "region-pool release lifetime smoke: rejected a pointer read completed before pool.release at -O$optimization" >&2
        cat "$WORK/before-release-O$optimization.log" >&2
        exit 1
    }
    [[ -s "$good_output" ]] || { echo "region-pool release lifetime smoke: did not emit LLVM for the live-before-release control at -O$optimization" >&2; exit 1; }
done

echo "region-pool release lifetime smoke OK: copied pointers are invalidated by direct, conditional, and nested-field release at -O0/-O2"
