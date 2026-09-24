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
ARENA_ALIAS_RESET_BAD="$ROOT/test/repro/arena_alias_reset_leak.elisa"
ARENA_ALIAS_RESET_GOOD="$ROOT/test/parity/fixtures/arena_alias_reset_live.elisa"
ARENA_HELPER_RESET_BAD="$ROOT/test/repro/arena_helper_reset_leak.elisa"
ARENA_HELPER_RESET_GOOD="$ROOT/test/parity/fixtures/arena_helper_reset_live.elisa"
ARENA_NAMED_RESET_BAD="$ROOT/test/repro/arena_named_reset_leak.elisa"
ARENA_NAMED_RESET_GOOD="$ROOT/test/parity/fixtures/arena_named_reset_live.elisa"
ARENA_OPAQUE_RESET_BAD="$ROOT/test/repro/arena_opaque_reset_leak.elisa"
ARENA_CALLBACK_RESET_BAD="$ROOT/test/repro/arena_callback_reset_leak.elisa"
ARENA_FORWARDED_CALLBACK_RESET_BAD="$ROOT/test/repro/arena_forwarded_callback_reset_leak.elisa"
ARENA_CAPTURED_CALLBACK_RESET_BAD="$ROOT/test/repro/arena_captured_callback_reset_leak.elisa"
ARENA_STATIC_EFFECT_RESET_BAD="$ROOT/test/repro/arena_static_effect_capture_reset_leak.elisa"
ARENA_CLOSURE_ALIAS_RESET_BAD="$ROOT/test/repro/arena_closure_alias_after_free.elisa"
ARENA_CLOSURE_ASSIGNMENT_RESET_BAD="$ROOT/test/repro/arena_closure_assignment_after_free.elisa"
ARENA_RETURNED_CLOSURE_RESET_BAD="$ROOT/test/repro/arena_returned_closure_after_free.elisa"
ARENA_CLOSURE_INTERNAL_RESET_BAD="$ROOT/test/repro/arena_closure_internal_reset_then_read.elisa"
INLINE_CLOSURE_STALE_BAD="$ROOT/test/repro/sview_region_inline_callback_after_destroy.elisa"
ARENA_TUPLE_CLOSURE_UNSUPPORTED="$ROOT/test/repro/arena_tuple_closure_after_free.elisa"
ARENA_CAPTURED_CLOSURE_LIVE="$ROOT/test/parity/fixtures/arena_captured_closure_live.elisa"
CONDITION_IF_BAD="$ROOT/test/repro/sview_region_condition_after_destroy.elisa"
CONDITION_WHILE_BAD="$ROOT/test/repro/sview_region_while_condition_after_destroy.elisa"
CONDITION_FOR_BAD="$ROOT/test/repro/sview_region_for_iterable_after_destroy.elisa"
CONDITION_MATCH_BAD="$ROOT/test/repro/sview_region_match_scrutinee_after_destroy.elisa"
VALUE_BLOCK_BAD="$ROOT/test/repro/sview_region_value_block_after_destroy.elisa"
VALUE_MATCH_BAD="$ROOT/test/repro/sview_region_match_value_after_destroy.elisa"
VALUE_BLOCK_READ_BAD="$ROOT/test/repro/sview_region_value_block_read_after_destroy.elisa"
VALUE_MATCH_READ_BAD="$ROOT/test/repro/sview_region_match_read_after_destroy.elisa"
ARENA_BLOCK_RESET_BAD="$ROOT/test/repro/arena_block_expression_reset_leak.elisa"
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

    arena_alias_reset_output="$WORK/arena-alias-reset-O$optimization"
    arena_alias_reset_log="$arena_alias_reset_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_alias_reset_output.ll" "$ARENA_ALIAS_RESET_BAD" >"$arena_alias_reset_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted an outer view after resetting its Arena through a copied alias at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_alias_reset_log" || {
        echo "destroyed view lifetime smoke: Arena& alias reset lost the source owner identity at O$optimization" >&2
        cat "$arena_alias_reset_log" >&2
        exit 1
    }
    [[ ! -e "$arena_alias_reset_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a stale view after alias reset at O$optimization" >&2; exit 1; }

    arena_alias_reset_live_output="$WORK/arena-alias-reset-live-O$optimization"
    arena_alias_reset_live_log="$arena_alias_reset_live_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_alias_reset_live_output" "$ARENA_ALIAS_RESET_GOOD" >"$arena_alias_reset_live_log" 2>&1 || {
        echo "destroyed view lifetime smoke: resetting an independent inner arena through its alias invalidated an outer view at O$optimization" >&2
        cat "$arena_alias_reset_live_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_alias_reset_live_output" >"$arena_alias_reset_live_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: independent outer view returned $run_status at O$optimization, expected 65" >&2
        cat "$arena_alias_reset_live_log.run" >&2
        exit 1
    }

    arena_helper_reset_output="$WORK/arena-helper-reset-O$optimization"
    arena_helper_reset_log="$arena_helper_reset_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_helper_reset_output.ll" "$ARENA_HELPER_RESET_BAD" >"$arena_helper_reset_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted an outer view after a helper reset its Arena& parameter at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_helper_reset_log" || {
        echo "destroyed view lifetime smoke: helper reset lost the source Arena& parameter identity at O$optimization" >&2
        cat "$arena_helper_reset_log" >&2
        exit 1
    }
    [[ ! -e "$arena_helper_reset_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a stale view after helper reset at O$optimization" >&2; exit 1; }

    arena_helper_live_output="$WORK/arena-helper-live-O$optimization"
    arena_helper_live_log="$arena_helper_live_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_helper_live_output" "$ARENA_HELPER_RESET_GOOD" >"$arena_helper_live_log" 2>&1 || {
        echo "destroyed view lifetime smoke: a non-resetting Arena& helper spuriously invalidated an outer view at O$optimization" >&2
        cat "$arena_helper_live_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_helper_live_output" >"$arena_helper_live_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: non-resetting helper control returned $run_status at O$optimization, expected 65" >&2
        cat "$arena_helper_live_log.run" >&2
        exit 1
    }

    arena_named_reset_output="$WORK/arena-named-reset-O$optimization"
    arena_named_reset_log="$arena_named_reset_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_named_reset_output.ll" "$ARENA_NAMED_RESET_BAD" >"$arena_named_reset_log" 2>&1; then
        echo "destroyed view lifetime smoke: named helper arguments invalidated the wrong owner at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "first"' "$arena_named_reset_log" || {
        echo "destroyed view lifetime smoke: named reset helper lost its target parameter identity at O$optimization" >&2
        cat "$arena_named_reset_log" >&2
        exit 1
    }
    [[ ! -e "$arena_named_reset_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a stale view after named reset at O$optimization" >&2; exit 1; }

    arena_named_live_output="$WORK/arena-named-reset-live-O$optimization"
    arena_named_live_log="$arena_named_live_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_named_live_output" "$ARENA_NAMED_RESET_GOOD" >"$arena_named_live_log" 2>&1 || {
        echo "destroying the named second Arena invalidated a view tied to the named kept Arena at O$optimization" >&2
        cat "$arena_named_live_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_named_live_output" >"$arena_named_live_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: named independent-owner control returned $run_status at O$optimization, expected 65" >&2
        cat "$arena_named_live_log.run" >&2
        exit 1
    }

    arena_opaque_reset_output="$WORK/arena-opaque-reset-O$optimization"
    arena_opaque_reset_log="$arena_opaque_reset_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_opaque_reset_output.ll" "$ARENA_OPAQUE_RESET_BAD" >"$arena_opaque_reset_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a stale view after an opaque external call received its Arena& at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_opaque_reset_log" || {
        echo "destroyed view lifetime smoke: opaque external call lost the passed arena dependency at O$optimization" >&2
        cat "$arena_opaque_reset_log" >&2
        exit 1
    }
    [[ ! -e "$arena_opaque_reset_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting an opaque external arena call at O$optimization" >&2; exit 1; }

    arena_callback_reset_output="$WORK/arena-callback-reset-O$optimization"
    arena_callback_reset_log="$arena_callback_reset_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_callback_reset_output.ll" "$ARENA_CALLBACK_RESET_BAD" >"$arena_callback_reset_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a stale view after an indirect callback received its Arena& at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_callback_reset_log" || {
        echo "destroyed view lifetime smoke: indirect callback rejection lost the passed arena dependency at O$optimization" >&2
        cat "$arena_callback_reset_log" >&2
        exit 1
    }
    [[ ! -e "$arena_callback_reset_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting an indirect arena callback at O$optimization" >&2; exit 1; }

    arena_forwarded_callback_output="$WORK/arena-forwarded-callback-reset-O$optimization"
    arena_forwarded_callback_log="$arena_forwarded_callback_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_forwarded_callback_output.ll" "$ARENA_FORWARDED_CALLBACK_RESET_BAD" >"$arena_forwarded_callback_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a stale view after a helper invoked its forwarded callback at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_forwarded_callback_log" || {
        echo "destroyed view lifetime smoke: forwarded callback rejection lost the Arena& parameter summary at O$optimization" >&2
        cat "$arena_forwarded_callback_log" >&2
        exit 1
    }
    [[ ! -e "$arena_forwarded_callback_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a forwarded callback at O$optimization" >&2; exit 1; }

    arena_captured_callback_output="$WORK/arena-captured-callback-reset-O$optimization"
    arena_captured_callback_log="$arena_captured_callback_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_captured_callback_output.ll" "$ARENA_CAPTURED_CALLBACK_RESET_BAD" >"$arena_captured_callback_log" 2>&1; then
        echo "destroyed view lifetime smoke: emitted LLVM for a captured reset callback with a stale view at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "first"' "$arena_captured_callback_log" || {
        echo "destroyed view lifetime smoke: captured callback rejection lost its captured arena dependency at O$optimization" >&2
        cat "$arena_captured_callback_log" >&2
        exit 1
    }
    [[ ! -e "$arena_captured_callback_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a captured arena callback at O$optimization" >&2; exit 1; }

    arena_static_effect_reset_output="$WORK/arena-static-effect-reset-O$optimization"
    arena_static_effect_reset_log="$arena_static_effect_reset_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_static_effect_reset_output.ll" "$ARENA_STATIC_EFFECT_RESET_BAD" >"$arena_static_effect_reset_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a stale view after a static-effect handler reset its captured arena at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_static_effect_reset_log" || {
        echo "destroyed view lifetime smoke: static-effect handler rejection lost its captured arena dependency at O$optimization" >&2
        cat "$arena_static_effect_reset_log" >&2
        exit 1
    }
    [[ ! -e "$arena_static_effect_reset_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a static-effect captured-arena reset at O$optimization" >&2; exit 1; }

    for closure_case in alias assignment returned; do
        case "$closure_case" in
            alias) closure_source="$ARENA_CLOSURE_ALIAS_RESET_BAD"; closure_region="alloc" ;;
            assignment) closure_source="$ARENA_CLOSURE_ASSIGNMENT_RESET_BAD"; closure_region="alloc" ;;
            returned) closure_source="$ARENA_RETURNED_CLOSURE_RESET_BAD"; closure_region="arena" ;;
        esac
        closure_output="$WORK/closure-$closure_case-O$optimization"
        closure_log="$closure_output.log"
        if "$STAGE1" -emit llvm "-O$optimization" -o "$closure_output.ll" "$closure_source" >"$closure_log" 2>&1; then
            echo "destroyed view lifetime smoke: accepted a closure with an arena-invalidated capture ($closure_case) at O$optimization" >&2
            exit 1
        fi
        rg -Fq "region dependency facts were invalidated by destroy of region \"$closure_region\"" "$closure_log" || {
            echo "destroyed view lifetime smoke: closure capture rejection lost its arena dependency ($closure_case) at O$optimization" >&2
            cat "$closure_log" >&2
            exit 1
        }
        [[ ! -e "$closure_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting an arena-invalidated closure capture ($closure_case) at O$optimization" >&2; exit 1; }
    done

    closure_internal_output="$WORK/closure-internal-reset-O$optimization"
    closure_internal_log="$closure_internal_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$closure_internal_output.ll" "$ARENA_CLOSURE_INTERNAL_RESET_BAD" >"$closure_internal_log" 2>&1; then
        echo "destroyed view lifetime smoke: emitted LLVM for a closure that resets its captured arena before reading its captured view at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$closure_internal_log" || {
        echo "destroyed view lifetime smoke: closure-internal reset rejection lost its captured arena dependency at O$optimization" >&2
        cat "$closure_internal_log" >&2
        exit 1
    }
    [[ ! -e "$closure_internal_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a closure-internal stale read at O$optimization" >&2; exit 1; }

    inline_closure_output="$WORK/inline-closure-stale-O$optimization"
    inline_closure_log="$inline_closure_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$inline_closure_output.ll" "$INLINE_CLOSURE_STALE_BAD" >"$inline_closure_log" 2>&1; then
        echo "destroyed view lifetime smoke: emitted LLVM for an inline callback capturing a destroyed view at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$inline_closure_log" || {
        echo "destroyed view lifetime smoke: inline callback rejection lost its captured region at O$optimization" >&2
        cat "$inline_closure_log" >&2
        exit 1
    }
    [[ ! -e "$inline_closure_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting an inline stale callback at O$optimization" >&2; exit 1; }

    captured_closure_live_output="$WORK/captured-closure-live-O$optimization"
    captured_closure_live_log="$captured_closure_live_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$captured_closure_live_output" "$ARENA_CAPTURED_CLOSURE_LIVE" >"$captured_closure_live_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rejected a closure called while its captured arena was live, despite freeing only an unrelated arena, at O$optimization" >&2
        cat "$captured_closure_live_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$captured_closure_live_output" >"$captured_closure_live_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: live captured-closure control returned $run_status at O$optimization, expected 65" >&2
        cat "$captured_closure_live_log.run" >&2
        exit 1
    }

    tuple_closure_output="$WORK/tuple-closure-unsupported-O$optimization"
    tuple_closure_log="$tuple_closure_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$tuple_closure_output.ll" "$ARENA_TUPLE_CLOSURE_UNSUPPORTED" >"$tuple_closure_log" 2>&1; then
        echo "destroyed view lifetime smoke: emitted LLVM for a tuple containing a capturing closure after its arena was freed at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'backend could not produce a linkable unit' "$tuple_closure_log" || {
        echo "destroyed view lifetime smoke: tuple closure was rejected for an unexpected reason at O$optimization" >&2
        cat "$tuple_closure_log" >&2
        exit 1
    }
    [[ ! -e "$tuple_closure_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for an unsupported tuple closure at O$optimization" >&2; exit 1; }

    for condition_case in if while for match; do
        case "$condition_case" in
            if) condition_source="$CONDITION_IF_BAD" ;;
            while) condition_source="$CONDITION_WHILE_BAD" ;;
            for) condition_source="$CONDITION_FOR_BAD" ;;
            match) condition_source="$CONDITION_MATCH_BAD" ;;
        esac
        condition_output="$WORK/condition-$condition_case-O$optimization"
        condition_log="$condition_output.log"
        if "$STAGE1" -emit llvm "-O$optimization" -o "$condition_output.ll" "$condition_source" >"$condition_log" 2>&1; then
            echo "destroyed view lifetime smoke: accepted a stale view used only in a $condition_case condition/iterable at O$optimization" >&2
            exit 1
        fi
        rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$condition_log" || {
            echo "destroyed view lifetime smoke: stale $condition_case expression lost its destroyed-region diagnostic at O$optimization" >&2
            cat "$condition_log" >&2
            exit 1
        }
        [[ ! -e "$condition_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a stale $condition_case expression at O$optimization" >&2; exit 1; }
    done

    for value_case in block match; do
        case "$value_case" in
            block) value_source="$VALUE_BLOCK_BAD" ;;
            match) value_source="$VALUE_MATCH_BAD" ;;
        esac
        value_output="$WORK/value-$value_case-O$optimization"
        value_log="$value_output.log"
        if "$STAGE1" -emit llvm "-O$optimization" -o "$value_output.ll" "$value_source" >"$value_log" 2>&1; then
            echo "destroyed view lifetime smoke: accepted a view derived through a $value_case value expression after its region was destroyed at O$optimization" >&2
            exit 1
        fi
        rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$value_log" || {
            echo "destroyed view lifetime smoke: stale $value_case result lost its destroyed-region diagnostic at O$optimization" >&2
            cat "$value_log" >&2
            exit 1
        }
        [[ ! -e "$value_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a stale $value_case result at O$optimization" >&2; exit 1; }
    done

    for read_case in block match; do
        case "$read_case" in
            block) read_source="$VALUE_BLOCK_READ_BAD" ;;
            match) read_source="$VALUE_MATCH_READ_BAD" ;;
        esac
        read_output="$WORK/value-read-$read_case-O$optimization"
        read_log="$read_output.log"
        if "$STAGE1" -emit llvm "-O$optimization" -o "$read_output.ll" "$read_source" >"$read_log" 2>&1; then
            echo "destroyed view lifetime smoke: accepted a stale read nested in a scalar-valued $read_case expression at O$optimization" >&2
            exit 1
        fi
        rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$read_log" || {
            echo "destroyed view lifetime smoke: nested $read_case read lost its destroyed-region diagnostic at O$optimization" >&2
            cat "$read_log" >&2
            exit 1
        }
        [[ ! -e "$read_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a nested stale $read_case read at O$optimization" >&2; exit 1; }
    done

    arena_block_reset_output="$WORK/arena-block-reset-O$optimization"
    arena_block_reset_log="$arena_block_reset_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_block_reset_output.ll" "$ARENA_BLOCK_RESET_BAD" >"$arena_block_reset_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a stale view after a reset hidden in a block expression at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "alloc"' "$arena_block_reset_log" || {
        echo "destroyed view lifetime smoke: block-expression reset lost its owner dependency at O$optimization" >&2
        cat "$arena_block_reset_log" >&2
        exit 1
    }
    [[ ! -e "$arena_block_reset_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after rejecting a block-expression stale view at O$optimization" >&2; exit 1; }

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
