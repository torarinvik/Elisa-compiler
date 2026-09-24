#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "destroyed view lifetime smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-destroyed-view.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

BAD="$ROOT/test/repro/sview_region_use_after_destroy.elisa"
GENERIC_BAD="$ROOT/test/repro/region_generic_struct_signature.elisa"
MULTI_GENERIC_BAD="$ROOT/test/repro/region_multiple_generic_dependencies.elisa"
JSON_HANDLE_BAD="$ROOT/test/repro/json_handle_after_arena_free.elisa"
JSON_REGION_MISMATCH_BAD="$ROOT/test/repro/json_handle_region_mismatch.elisa"
SHADOW_REBIND_BAD="$ROOT/test/repro/shadowed_region_generic_rebind.elisa"
OPTIONAL_BAD="$ROOT/test/repro/sview_optional_region_use_after_destroy.elisa"
SHADOW_BAD="$ROOT/test/repro/region_shadow_inner_use_after_destroy.elisa"
JSON_VIEW_BAD="$ROOT/test/repro/json_view_after_arena_free.elisa"
ARENA_VIEW_BAD="$ROOT/test/repro/manual_arena_free_use_after_region.elisa"
ARENA_OWNER_SHADOW_BAD="$ROOT/test/repro/arena_owner_shadow_reset_leak.elisa"
ARENA_OWNER_SHADOW_GOOD="$ROOT/test/parity/fixtures/arena_owner_shadow_reset_live.elisa"
GOOD="$ROOT/test/parity/fixtures/sview_region_live_use.elisa"
SHADOW_GOOD="$ROOT/test/parity/fixtures/region_shadow_outer_live_use.elisa"
LAST_USE="$ROOT/test/repro/sview_region_last_use_before_destroy.elisa"
for optimization in 0 2; do
    bad_output="$WORK/bad-O$optimization"
    bad_log="$bad_output.log"
    if "$STAGE1" -emit exe "-O$optimization" -o "$bad_output" "$BAD" >"$bad_log" 2>&1; then
        echo "destroyed view lifetime smoke: Stage1 accepted a copied view after its region was destroyed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$bad_log" || {
        echo "destroyed view lifetime smoke: missing destroyed-region diagnostic at O$optimization" >&2
        cat "$bad_log" >&2
        exit 1
    }
    [[ ! -e "$bad_output" ]] || { echo "destroyed view lifetime smoke: wrote executable for rejected stale view at O$optimization" >&2; exit 1; }

    generic_output="$WORK/generic-wrapper-O$optimization"
    generic_log="$generic_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$generic_output.ll" "$GENERIC_BAD" >"$generic_log" 2>&1; then
        echo "destroyed view lifetime smoke: Stage1 accepted a generic region-carrying wrapper after its region was destroyed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$generic_log" || {
        echo "destroyed view lifetime smoke: generic wrapper rejection lost its region dependency at O$optimization" >&2
        cat "$generic_log" >&2
        exit 1
    }
    [[ ! -e "$generic_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected generic wrapper at O$optimization" >&2; exit 1; }

    multi_generic_output="$WORK/multiple-generic-O$optimization"
    multi_generic_log="$multi_generic_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$multi_generic_output.ll" "$MULTI_GENERIC_BAD" >"$multi_generic_log" 2>&1; then
        echo "destroyed view lifetime smoke: Stage1 accepted the first of two stale generic region dependencies at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "first"' "$multi_generic_log" || {
        echo "destroyed view lifetime smoke: multiple generic dependencies lost the destroyed first region at O$optimization" >&2
        cat "$multi_generic_log" >&2
        exit 1
    }
    [[ ! -e "$multi_generic_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected multi-region wrapper at O$optimization" >&2; exit 1; }

    json_output="$WORK/json-handle-O$optimization"
    json_log="$json_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$json_output.ll" "$JSON_HANDLE_BAD" >"$json_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted JSON handle access after its backing arena was freed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "arena"' "$json_log" || {
        echo "destroyed view lifetime smoke: JSON handle rejection lost its arena dependency at O$optimization" >&2
        cat "$json_log" >&2
        exit 1
    }
    [[ ! -e "$json_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected stale JSON handle at O$optimization" >&2; exit 1; }

    json_mismatch_output="$WORK/json-handle-region-mismatch-O$optimization"
    json_mismatch_log="$json_mismatch_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$json_mismatch_output.ll" "$JSON_REGION_MISMATCH_BAD" >"$json_mismatch_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a JSON handle parameterized by a different arena at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'variable "value" expects JsonValueHandle, got JsonValueHandle' "$json_mismatch_log" || {
        echo "destroyed view lifetime smoke: cross-arena generic return lost its source lifetime at O$optimization" >&2
        cat "$json_mismatch_log" >&2
        exit 1
    }
    [[ ! -e "$json_mismatch_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected cross-arena JSON handle at O$optimization" >&2; exit 1; }

    shadow_rebind_output="$WORK/shadowed-region-generic-rebind-O$optimization"
    shadow_rebind_log="$shadow_rebind_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$shadow_rebind_output.ll" "$SHADOW_REBIND_BAD" >"$shadow_rebind_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted rebinding an outer generic handle to an inner same-name region at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'Box' "$shadow_rebind_log" || {
        echo "destroyed view lifetime smoke: same-name region rebind rejection did not report a structural type mismatch at O$optimization" >&2
        cat "$shadow_rebind_log" >&2
        exit 1
    }
    [[ ! -e "$shadow_rebind_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected cross-region rebind at O$optimization" >&2; exit 1; }

    optional_output="$WORK/optional-view-after-destroy-O$optimization"
    optional_log="$optional_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$optional_output.ll" "$OPTIONAL_BAD" >"$optional_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a present optional view after its region was destroyed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$optional_log" || {
        echo "destroyed view lifetime smoke: optional view rejection lost its backing-region dependency at O$optimization" >&2
        cat "$optional_log" >&2
        exit 1
    }
    [[ ! -e "$optional_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected optional stale view at O$optimization" >&2; exit 1; }

    shadow_bad_output="$WORK/shadow-inner-after-destroy-O$optimization"
    shadow_bad_log="$shadow_bad_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$shadow_bad_output.ll" "$SHADOW_BAD" >"$shadow_bad_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted an inner shadowed-region view after destroy at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "r"' "$shadow_bad_log" || {
        echo "destroyed view lifetime smoke: inner shadowed-region rejection lost its region identity at O$optimization" >&2
        cat "$shadow_bad_log" >&2
        exit 1
    }
    [[ ! -e "$shadow_bad_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected shadowed-region use at O$optimization" >&2; exit 1; }

    json_view_output="$WORK/json-view-after-arena-free-O$optimization"
    json_view_log="$json_view_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$json_view_output.ll" "$JSON_VIEW_BAD" >"$json_view_log" 2>&1; then
        echo "destroyed view lifetime smoke: Stage1 accepted a copied JSON string view after its arena was freed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "arena"' "$json_view_log" || {
        echo "destroyed view lifetime smoke: JSON string view rejection lost its freed arena dependency at O$optimization" >&2
        cat "$json_view_log" >&2
        exit 1
    }
    [[ ! -e "$json_view_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected post-free JSON view at O$optimization" >&2; exit 1; }

    arena_view_output="$WORK/view-after-arena-free-O$optimization"
    arena_view_log="$arena_view_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_view_output.ll" "$ARENA_VIEW_BAD" >"$arena_view_log" 2>&1; then
        echo "destroyed view lifetime smoke: Stage1 accepted an explicitly arena-bound view after arena_free at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "arena"' "$arena_view_log" || {
        echo "destroyed view lifetime smoke: explicit arena-bound view rejection lost the arena dependency at O$optimization" >&2
        cat "$arena_view_log" >&2
        exit 1
    }
    [[ ! -e "$arena_view_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a rejected arena-bound view at O$optimization" >&2; exit 1; }

    arena_owner_shadow_output="$WORK/arena-owner-shadow-reset-O$optimization"
    arena_owner_shadow_log="$arena_owner_shadow_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_owner_shadow_output.ll" "$ARENA_OWNER_SHADOW_BAD" >"$arena_owner_shadow_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted an outer view after reset through its same-name Arena& owner at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_owner_shadow_log" || {
        echo "destroyed view lifetime smoke: same-name Arena& owner reset lost the outer region identity at O$optimization" >&2
        cat "$arena_owner_shadow_log" >&2
        exit 1
    }
    [[ ! -e "$arena_owner_shadow_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for an outer stale view after same-name owner reset at O$optimization" >&2; exit 1; }

    arena_owner_shadow_live_output="$WORK/arena-owner-shadow-reset-live-O$optimization"
    arena_owner_shadow_live_log="$arena_owner_shadow_live_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_owner_shadow_live_output" "$ARENA_OWNER_SHADOW_GOOD" >"$arena_owner_shadow_live_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected an outer view after only the inner same-name owner was reset at O$optimization" >&2
        cat "$arena_owner_shadow_live_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_owner_shadow_live_output" >"$arena_owner_shadow_live_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: live outer view returned $run_status at O$optimization, expected 65" >&2
        cat "$arena_owner_shadow_live_log.run" >&2
        exit 1
    }

    for invalidation in reset rewind; do
        invalidation_source="$ROOT/test/repro/manual_arena_${invalidation}_use_after_region.elisa"
        invalidation_output="$WORK/view-after-arena-${invalidation}-O$optimization"
        invalidation_log="$invalidation_output.log"
        if "$STAGE1" -emit llvm "-O$optimization" -o "$invalidation_output.ll" "$invalidation_source" >"$invalidation_log" 2>&1; then
            echo "destroyed view lifetime smoke: Stage1 accepted an arena-bound view after arena_${invalidation} at O$optimization" >&2
            exit 1
        fi
        rg -Fq 'region dependency facts were invalidated by destroy of region "arena"' "$invalidation_log" || {
            echo "destroyed view lifetime smoke: arena_${invalidation} rejection lost the arena dependency at O$optimization" >&2
            cat "$invalidation_log" >&2
            exit 1
        }
        [[ ! -e "$invalidation_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejected arena_${invalidation} use at O$optimization" >&2; exit 1; }
    done

    good_output="$WORK/good-O$optimization"
    good_log="$good_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$good_output" "$GOOD" >"$good_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected a live region-backed view at O$optimization" >&2
        cat "$good_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$good_output" >"$good_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 1 ]] || {
        echo "destroyed view lifetime smoke: live view returned $run_status at O$optimization, expected length 1" >&2
        cat "$good_log.run" >&2
        exit 1
    }

    last_use_output="$WORK/last-use-O$optimization"
    last_use_log="$last_use_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$last_use_output" "$LAST_USE" >"$last_use_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected a view whose last use precedes destroy at O$optimization" >&2
        cat "$last_use_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$last_use_output" >"$last_use_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 0 ]] || {
        echo "destroyed view lifetime smoke: last-use-before-destroy control returned $run_status at O$optimization" >&2
        cat "$last_use_log.run" >&2
        exit 1
    }

    optional_good_output="$WORK/optional-view-live-O$optimization"
    optional_good_log="$optional_good_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$optional_good_output" "$ROOT/test/parity/fixtures/sview_optional_region_live_use.elisa" >"$optional_good_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected a present optional view used before destroy, or an absent optional afterward at O$optimization" >&2
        cat "$optional_good_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$optional_good_output" >"$optional_good_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 0 ]] || {
        echo "destroyed view lifetime smoke: optional live/absent control returned $run_status at O$optimization" >&2
        cat "$optional_good_log.run" >&2
        exit 1
    }

    shadow_good_output="$WORK/shadow-outer-live-O$optimization"
    shadow_good_log="$shadow_good_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$shadow_good_output" "$SHADOW_GOOD" >"$shadow_good_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected an outer value after an inner same-name region was destroyed at O$optimization" >&2
        cat "$shadow_good_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$shadow_good_output" >"$shadow_good_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 0 ]] || {
        echo "destroyed view lifetime smoke: outer shadowed-region control returned $run_status at O$optimization" >&2
        cat "$shadow_good_log.run" >&2
        exit 1
    }

    shadow_rebind_good_output="$WORK/shadowed-region-generic-rebind-live-O$optimization"
    shadow_rebind_good_log="$shadow_rebind_good_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$shadow_rebind_good_output" "$ROOT/test/parity/fixtures/shadowed_region_generic_rebind_live.elisa" >"$shadow_rebind_good_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected a same-region generic handle rebind at O$optimization" >&2
        cat "$shadow_rebind_good_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$shadow_rebind_good_output" >"$shadow_rebind_good_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 0 ]] || {
        echo "destroyed view lifetime smoke: same-region generic rebind control returned $run_status at O$optimization, expected 0" >&2
        cat "$shadow_rebind_good_log.run" >&2
        exit 1
    }
done

echo "destroyed view lifetime smoke OK: stale uses are rejected; live, last-use, and shadowed-region controls pass at O0/O2"
