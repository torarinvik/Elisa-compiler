# Arena alias and reset cases, sourced once per optimization level.
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

    arena_alias_rebind_output="$WORK/arena-alias-rebind-reset-O$optimization"
    arena_alias_rebind_log="$arena_alias_rebind_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_alias_rebind_output.ll" "$ARENA_ALIAS_REBIND_RESET_BAD" >"$arena_alias_rebind_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a view after resetting the arena currently designated by a rebound Arena& at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "second"' "$arena_alias_rebind_log" || {
        echo "destroyed view lifetime smoke: Arena& rebind did not transfer its invalidation identity at O$optimization" >&2
        cat "$arena_alias_rebind_log" >&2
        exit 1
    }
    [[ ! -e "$arena_alias_rebind_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a stale view after Arena& rebind at O$optimization" >&2; exit 1; }

    arena_alias_conditional_output="$WORK/arena-alias-conditional-rebind-O$optimization"
    arena_alias_conditional_log="$arena_alias_conditional_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_alias_conditional_output.ll" "$ARENA_ALIAS_CONDITIONAL_REBIND_RESET_BAD" >"$arena_alias_conditional_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted a stale view after a branch-dependent Arena& rebind at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "first"' "$arena_alias_conditional_log" || {
        echo "destroyed view lifetime smoke: conditional Arena& rebind failed to retain the original owner possibility at O$optimization" >&2
        cat "$arena_alias_conditional_log" >&2
        exit 1
    }
    [[ ! -e "$arena_alias_conditional_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a stale view after conditional Arena& rebind at O$optimization" >&2; exit 1; }

    arena_alias_copy_conditional_output="$WORK/arena-alias-copy-conditional-O$optimization"
    arena_alias_copy_conditional_log="$arena_alias_copy_conditional_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_alias_copy_conditional_output.ll" "$ARENA_ALIAS_COPY_CONDITIONAL_REBIND_RESET_BAD" >"$arena_alias_copy_conditional_log" 2>&1; then
        echo "destroyed view lifetime smoke: copying a branch-rebound Arena& dropped a possible stale owner at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "first"' "$arena_alias_copy_conditional_log" || {
        echo "destroyed view lifetime smoke: copied conditional alias failed to retain the original owner root at O$optimization" >&2
        cat "$arena_alias_copy_conditional_log" >&2
        exit 1
    }
    [[ ! -e "$arena_alias_copy_conditional_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for a stale copied alias at O$optimization" >&2; exit 1; }

    arena_alias_control_join_output="$WORK/arena-alias-control-join-O$optimization"
    arena_alias_control_join_log="$arena_alias_control_join_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_alias_control_join_output.ll" "$ARENA_ALIAS_CONTROL_JOIN_BAD" >"$arena_alias_control_join_log" 2>&1; then
        echo "destroyed view lifetime smoke: accepted an alias reset with skipped while/for/match paths at O$optimization" >&2
        exit 1
    fi
    for expected_owner in while_alloc for_alloc match_alloc; do
        rg -Fq "region dependency facts were invalidated by destroy of region \"$expected_owner\"" "$arena_alias_control_join_log" || {
            echo "destroyed view lifetime smoke: control-flow owner join lost $expected_owner at O$optimization" >&2
            cat "$arena_alias_control_join_log" >&2
            exit 1
        }
    done
    [[ ! -e "$arena_alias_control_join_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM for stale views after a control-flow alias reset at O$optimization" >&2; exit 1; }

    arena_alias_conditional_live_output="$WORK/arena-alias-conditional-live-O$optimization"
    arena_alias_conditional_live_log="$arena_alias_conditional_live_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_alias_conditional_live_output" "$ARENA_ALIAS_CONDITIONAL_REBIND_LIVE" >"$arena_alias_conditional_live_log" 2>&1 || {
        echo "destroyed view lifetime smoke: conditional reset spuriously invalidated an unrelated third-arena view at O$optimization" >&2
        cat "$arena_alias_conditional_live_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_alias_conditional_live_output" >"$arena_alias_conditional_live_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 67 ]] || {
        echo "destroyed view lifetime smoke: unrelated-arena conditional control returned $run_status at O$optimization, expected 67" >&2
        cat "$arena_alias_conditional_live_log.run" >&2
        exit 1
    }

    arena_alias_both_arms_output="$WORK/arena-alias-both-arms-live-O$optimization"
    arena_alias_both_arms_log="$arena_alias_both_arms_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_alias_both_arms_output" "$ARENA_ALIAS_BOTH_IF_ARMS_LIVE" >"$arena_alias_both_arms_log" 2>&1 || {
        echo "destroyed view lifetime smoke: both if arms rebind away from the first owner, but it was still considered destroyable at O$optimization" >&2
        cat "$arena_alias_both_arms_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_alias_both_arms_output" >"$arena_alias_both_arms_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: both-arm rebind control returned $run_status at O$optimization, expected 65" >&2
        cat "$arena_alias_both_arms_log.run" >&2
        exit 1
    }

    arena_alias_exhaustive_match_output="$WORK/arena-alias-exhaustive-match-live-O$optimization"
    arena_alias_exhaustive_match_log="$arena_alias_exhaustive_match_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_alias_exhaustive_match_output" "$ARENA_ALIAS_EXHAUSTIVE_MATCH_LIVE" >"$arena_alias_exhaustive_match_log" 2>&1 || {
        echo "destroyed view lifetime smoke: exhaustive match arms rebind away from the first owner, but it was still considered destroyable at O$optimization" >&2
        cat "$arena_alias_exhaustive_match_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_alias_exhaustive_match_output" >"$arena_alias_exhaustive_match_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: exhaustive-match rebind control returned $run_status at O$optimization, expected 65" >&2
        cat "$arena_alias_exhaustive_match_log.run" >&2
        exit 1
    }

    arena_alias_guarded_match_output="$WORK/arena-alias-guarded-match-O$optimization"
    arena_alias_guarded_match_log="$arena_alias_guarded_match_output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$arena_alias_guarded_match_output.ll" "$ARENA_ALIAS_GUARDED_MATCH_BAD" >"$arena_alias_guarded_match_log" 2>&1; then
        echo "destroyed view lifetime smoke: guarded match binding was treated as exhaustive at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "first"' "$arena_alias_guarded_match_log" || {
        echo "destroyed view lifetime smoke: guarded match did not preserve the no-arm owner path at O$optimization" >&2
        cat "$arena_alias_guarded_match_log" >&2
        exit 1
    }
    [[ ! -e "$arena_alias_guarded_match_output.ll" ]] || { echo "destroyed view lifetime smoke: wrote LLVM after a guarded-match stale-view diagnostic at O$optimization" >&2; exit 1; }

    arena_alias_rebind_live_output="$WORK/arena-alias-rebind-live-O$optimization"
    arena_alias_rebind_live_log="$arena_alias_rebind_live_output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$arena_alias_rebind_live_output" "$ARENA_ALIAS_REBIND_RESET_GOOD" >"$arena_alias_rebind_live_log" 2>&1 || {
        echo "destroyed view lifetime smoke: rebinding an Arena& spuriously invalidated the old arena's view at O$optimization" >&2
        cat "$arena_alias_rebind_live_log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$arena_alias_rebind_live_output" >"$arena_alias_rebind_live_log.run" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 65 ]] || {
        echo "destroyed view lifetime smoke: rebound-alias precision control returned $run_status at O$optimization, expected 65" >&2
        cat "$arena_alias_rebind_live_log.run" >&2
        exit 1
    }

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

