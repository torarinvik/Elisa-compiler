# Catch and fallible-value source cases, sourced by try_fallible_smoke.sh.
catch_success_alias_nonfallible=$(printf 'error E:\n    Bad\ndef load() -> i64 error[E]:\n    return 1\ndef bad() -> i64:\n    result = catch load():\n        success:\n            success\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$catch_success_alias_nonfallible"

catch_success_arithmetic_alias_nonfallible=$(printf 'error E:\n    Bad\ndef load() -> i64 error[E]:\n    return 1\ndef bad() -> i64:\n    result = catch load():\n        success:\n            success\n        error problem:\n            0\n    return try (result + 1)\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$catch_success_arithmetic_alias_nonfallible"

catch_success_bool_alias_nonfallible=$(printf 'error E:\n    Bad\ndef load_flag() -> bool error[E]:\n    return true\ndef bad() -> bool:\n    result = catch load_flag():\n        success:\n            success\n        error problem:\n            false\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$catch_success_bool_alias_nonfallible"

catch_success_bool_arm_try_nonfallible=$(printf 'error E:\n    Bad\ndef load_flag() -> bool error[E]:\n    return true\ndef bad() -> bool:\n    return catch load_flag():\n        success:\n            try success\n        error problem:\n            false\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$catch_success_bool_arm_try_nonfallible"

catch_success_identifier_string_alias_nonfallible=$(printf 'error E:\n    Bad\ndef load_text() -> string error[E]:\n    return "loaded"\ndef bad() -> string:\n    cached = load_text()\n    result = catch cached:\n        success:\n            success\n        error problem:\n            "fallback"\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$catch_success_identifier_string_alias_nonfallible"

catch_success_arm_try_nonfallible=$(printf 'error E:\n    Bad\ndef load() -> i64 error[E]:\n    return 1\ndef bad() -> i64:\n    result = catch load():\n        success:\n            try success\n        error problem:\n            0\n    return result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$catch_success_arm_try_nonfallible"

catch_variant_name_does_not_bind_success_payload=$(printf 'error E:\n    Problem\nerror F:\n    Other\ndef mismatch(Problem: i64 error[E]) -> i64 error[F]:\n    return catch Problem:\n        success:\n            1\n        Problem:\n            return try Problem\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$catch_variant_name_does_not_bind_success_payload" || {
    echo "try_fallible FAILED: fieldless Catch error variant shadowed the outer fallible value: $catch_variant_name_does_not_bind_success_payload"
    exit 1
}
! grep -q 'try requires a fallible expression' <<< "$catch_variant_name_does_not_bind_success_payload"

typed_local_error_union_catch_payload=$(printf 'error E:\n    Bad\ndef load() -> i64 error[E]:\n    return 1\ndef bad() -> i64:\n    wrapped: i64 error[E] = load()\n    result = catch wrapped:\n        success:\n            success\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$typed_local_error_union_catch_payload" || {
    echo "try_fallible FAILED: typed error-union local lost its nonfallible success-payload fact: $typed_local_error_union_catch_payload"
    exit 1
}

catch_terminated_arm_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad() -> i64 error[E]:\n    result = catch load_e():\n        success:\n            return 1\n            copied = load_f()\n            copied\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_terminated_arm_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$catch_terminated_arm_ignores_unreachable_family" || {
    echo "try_fallible FAILED: terminating Catch arm failed to leave only the reachable nonfallible result: $catch_terminated_arm_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning E' <<< "$catch_terminated_arm_ignores_unreachable_family"

catch_terminated_boolean_match_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad() -> i64 error[E]:\n    result = catch load_e():\n        success:\n            match true:\n                true:\n                    return 1\n                false:\n                    return 2\n            copied = load_f()\n            copied\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_terminated_boolean_match_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$catch_terminated_boolean_match_ignores_unreachable_family" || {
    echo "try_fallible FAILED: exhaustive terminating boolean Match failed to exclude its unreachable Catch-arm tail: $catch_terminated_boolean_match_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning E' <<< "$catch_terminated_boolean_match_ignores_unreachable_family"

catch_literal_true_if_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad() -> i64 error[E]:\n    result = catch load_e():\n        success:\n            if true:\n                return 1\n            copied = load_f()\n            copied\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_literal_true_if_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$catch_literal_true_if_ignores_unreachable_family" || {
    echo "try_fallible FAILED: literal-true terminating If failed to exclude its unreachable Catch-arm tail: $catch_literal_true_if_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning E' <<< "$catch_literal_true_if_ignores_unreachable_family"

catch_terminated_scoped_block_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad() -> i64 error[E]:\n    result = catch load_e():\n        success:\n            can Abort.Panic:\n                return 1\n            copied = load_f()\n            copied\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_terminated_scoped_block_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$catch_terminated_scoped_block_ignores_unreachable_family" || {
    echo "try_fallible FAILED: terminating scoped block failed to exclude its unreachable Catch-arm tail: $catch_terminated_scoped_block_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning E' <<< "$catch_terminated_scoped_block_ignores_unreachable_family"

catch_aborting_call_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad() -> i64 error[E] can[Abort.Panic]:\n    result = catch load_e():\n        success:\n            panic()\n            copied = load_f()\n            copied\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_aborting_call_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$catch_aborting_call_ignores_unreachable_family" || {
    echo "try_fallible FAILED: aborting Catch-arm expression failed to exclude its unreachable tail: $catch_aborting_call_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning E' <<< "$catch_aborting_call_ignores_unreachable_family"

# A Catch expression whose guarded expression aborts has no value, so its dead tail
# must not contribute a fallible source family to the surrounding Catch result.
catch_nested_aborting_expression_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad() -> i64 error[E] can[Abort.Panic]:\n    result = catch load_e():\n        success:\n            nested = catch panic():\n                result:\n                    0\n                error problem:\n                    return 1\n            copied = load_f()\n            copied\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_nested_aborting_expression_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$catch_nested_aborting_expression_ignores_unreachable_family" || {
    echo "try_fallible FAILED: terminating nested Catch failed to exclude its unreachable tail: $catch_nested_aborting_expression_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning E' <<< "$catch_nested_aborting_expression_ignores_unreachable_family"

catch_nested_terminating_all_handlers_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\n    More\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad() -> i64 error[E] can[Abort.Panic]:\n    result = catch load_e():\n        success:\n            nested = catch load_f():\n                result:\n                    panic()\n                F.Other:\n                    panic()\n                F.More:\n                    panic()\n            copied = load_f()\n            copied\n        error problem:\n            0\n    return try result\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_nested_terminating_all_handlers_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$catch_nested_terminating_all_handlers_ignores_unreachable_family" || {
    echo "try_fallible FAILED: terminating Catch success and error handlers failed to exclude their unreachable tail: $catch_nested_terminating_all_handlers_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning E' <<< "$catch_nested_terminating_all_handlers_ignores_unreachable_family"

# A nested Catch's returning error handler remains a possible source even when
# each success arm exits the enclosing function.
nested_catch_recovery_branch_keeps_fallible_family=$(cat "$REPO_ROOT/test/repro/try_nested_catch_recovery_branch.elisa" | "$RPT")
grep -q '^P 0$' <<< "$nested_catch_recovery_branch_keeps_fallible_family" || {
    echo "try_fallible FAILED: nested Catch recovery fixture did not parse: $nested_catch_recovery_branch_keeps_fallible_family"
    exit 1
}
grep -q '^D 1$' <<< "$nested_catch_recovery_branch_keeps_fallible_family"
grep -q 'cannot propagate F from a function returning E' <<< "$nested_catch_recovery_branch_keeps_fallible_family" || {
    echo "try_fallible FAILED: nested Catch recovery branch lost the fallible F family: $nested_catch_recovery_branch_keeps_fallible_family"
    exit 1
}

match_aborting_guard_ignores_unreachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad(flag: bool) -> i64 can[Abort.Panic]:\n    value = match flag:\n        true if panic(): load_f()\n        false: 1\n    return try value\n' | "$RPT")
grep -q '^P 0$' <<< "$match_aborting_guard_ignores_unreachable_family"
grep -q 'try requires a fallible expression' <<< "$match_aborting_guard_ignores_unreachable_family" || {
    echo "try_fallible FAILED: aborting Match guard contributed an unreachable family: $match_aborting_guard_ignores_unreachable_family"
    exit 1
}
! grep -q 'cannot propagate F from a function returning' <<< "$match_aborting_guard_ignores_unreachable_family"

catch_raise_recovery_guard_keeps_match_arm_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef bad() -> i64 error[E]:\n    value = match true:\n        true if catch raise E.Bad:\n            success:\n                false\n            error problem:\n                true\n            : load_e()\n        false: 0\n    return try value\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_raise_recovery_guard_keeps_match_arm_family"
! grep -q 'try requires a fallible expression' <<< "$catch_raise_recovery_guard_keeps_match_arm_family" || {
    echo "try_fallible FAILED: a Catch that recovers from raise was treated as an aborting Match guard: $catch_raise_recovery_guard_keeps_match_arm_family"
    exit 1
}

catch_raise_selected_if_recovery_guard_keeps_match_arm_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef bad() -> i64 error[E]:\n    value = match true:\n        true if catch (raise E.Bad if true else load_e()):\n            success:\n                false\n            error problem:\n                true\n            : load_e()\n        false: 0\n    return try value\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_raise_selected_if_recovery_guard_keeps_match_arm_family"
! grep -q 'try requires a fallible expression' <<< "$catch_raise_selected_if_recovery_guard_keeps_match_arm_family" || {
    echo "try_fallible FAILED: a Catch handler failed to recover from a statically selected raise branch: $catch_raise_selected_if_recovery_guard_keeps_match_arm_family"
    exit 1
}

catch_mixed_raise_panic_recovery_guard_keeps_match_arm_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef bad(flag: bool) -> i64 error[E] can[Abort.Panic]:\n    value = match true:\n        true if catch (raise E.Bad if flag else panic()):\n            success:\n                false\n            error problem:\n                true\n            : load_e()\n        false: 0\n    return try value\n' | "$RPT")
grep -q '^P 0$' <<< "$catch_mixed_raise_panic_recovery_guard_keeps_match_arm_family"
! grep -q 'try requires a fallible expression' <<< "$catch_mixed_raise_panic_recovery_guard_keeps_match_arm_family" || {
    echo "try_fallible FAILED: Catch recovery lost the raise path when another guarded path panics: $catch_mixed_raise_panic_recovery_guard_keeps_match_arm_family"
    exit 1
}

catch_success_optional_payload_try=$(printf 'error E:\n    Bad\ndef load() -> i64? error[E]:\n    return 1\ndef good() -> i64? error[E]:\n    return catch load():\n        success:\n            try success\n        error problem:\n            null\n' | "$RPT")
! grep -q 'try requires a fallible expression' <<< "$catch_success_optional_payload_try"

# Direct bare-T returns use the unique matching formal argument. Catch strips only the
# wrapper's outer E family and preserves a fallible T payload.
catch_success_generic_error_union_payload=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef wrap[T](value: T) -> T error[E]:\n    return value\ndef good(value: i64 error[F]) -> i64 error[F]:\n    return catch wrap(value):\n        success:\n            try success\n        error problem:\n            0\n' | "$RPT")
! grep -q 'try requires a fallible expression' <<< "$catch_success_generic_error_union_payload"
grep -q '^D 0$' <<< "$catch_success_generic_error_union_payload"
grep -q '^P 0$' <<< "$catch_success_generic_error_union_payload"

catch_success_generic_error_union_payload_mismatch=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef wrap[T](value: T) -> T error[E]:\n    return value\ndef mismatch(value: i64 error[F]) -> i64 error[E]:\n    return catch wrap(value):\n        success:\n            try success\n        error problem:\n            0\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$catch_success_generic_error_union_payload_mismatch" || {
    echo "try_fallible FAILED: generic Catch success payload lost its inner error family: $catch_success_generic_error_union_payload_mismatch"
    exit 1
}
! grep -q 'try requires a fallible expression' <<< "$catch_success_generic_error_union_payload_mismatch"
! grep -q 'cannot propagate E from a function returning E' <<< "$catch_success_generic_error_union_payload_mismatch"

catch_success_generic_error_union_payload_alias_mismatch=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef wrap[T](value: T) -> T error[E]:\n    return value\ndef mismatch(value: i64 error[F]) -> i64 error[E]:\n    wrapped = wrap(value)\n    return catch wrapped:\n        success:\n            try success\n        error problem:\n            0\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$catch_success_generic_error_union_payload_alias_mismatch" || {
    echo "try_fallible FAILED: generic Catch success payload lost its inner family through an alias: $catch_success_generic_error_union_payload_alias_mismatch"
    exit 1
}
! grep -q 'try requires a fallible expression' <<< "$catch_success_generic_error_union_payload_alias_mismatch"

generic_return_alias_try=$(printf 'error E:\n    Bad\ndef identity[T](value: T) -> T:\n    return value\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    copied = identity(value)\n    return try copied\n' | "$RPT")
! grep -q 'try requires a fallible expression' <<< "$generic_return_alias_try"
grep -q '^D 0$' <<< "$generic_return_alias_try"
grep -q '^P 0$' <<< "$generic_return_alias_try"

generic_return_alias_family_mismatch=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef identity[T](value: T) -> T:\n    return value\ndef mismatch(value: i64 error[E]) -> i64 error[F]:\n    copied = identity(value)\n    return try copied\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$generic_return_alias_family_mismatch" || {
    echo "try_fallible FAILED: generic direct-T return lost its actual error family: $generic_return_alias_family_mismatch"
    exit 1
}
! grep -q 'try requires a fallible expression' <<< "$generic_return_alias_family_mismatch"
grep -q '^P 0$' <<< "$generic_return_alias_family_mismatch"

generic_return_mixed_named_family_mismatch=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef select[T](prefix: i64, value: T, marker: i64) -> T:\n    return value\ndef mismatch(value: i64 error[E]) -> i64 error[F]:\n    copied = select(0, value, marker: 1)\n    return try copied\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$generic_return_mixed_named_family_mismatch" || {
    echo "try_fallible FAILED: mixed positional/named generic return lost its actual error family: $generic_return_mixed_named_family_mismatch"
    exit 1
}
! grep -q 'try requires a fallible expression' <<< "$generic_return_mixed_named_family_mismatch"
grep -q '^P 0$' <<< "$generic_return_mixed_named_family_mismatch"

conditional_fallible_alias=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load() -> i64 error[E]:\n    return 1\ndef mismatch(flag: bool) -> i64 error[F]:\n    value = load() if flag else load()\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$conditional_fallible_alias"

conditional_fallible_direct=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load() -> i64 error[E]:\n    return 1\ndef mismatch(flag: bool) -> i64 error[F]:\n    return try (load() if flag else load())\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$conditional_fallible_direct"

conditional_literal_true_ignores_dead_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef mismatch() -> i64 error[F]:\n    value = load_e() if true else load_f()\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$conditional_literal_true_ignores_dead_family" || {
    echo "try_fallible FAILED: literal condition lost the reachable branch's error family: $conditional_literal_true_ignores_dead_family"
    exit 1
}
! grep -q 'try requires a fallible expression' <<< "$conditional_literal_true_ignores_dead_family"
grep -q '^P 0$' <<< "$conditional_literal_true_ignores_dead_family"

conditional_aborting_arm_keeps_reachable_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_f() -> i64 error[F]:\n    return 2\ndef mismatch(flag: bool) -> i64 error[E] can[Abort.Panic]:\n    value = panic() if flag else load_f()\n    return try value\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$conditional_aborting_arm_keeps_reachable_family" || {
    echo "try_fallible FAILED: aborting conditional arm erased the reachable family: $conditional_aborting_arm_keeps_reachable_family"
    exit 1
}
! grep -q 'try requires a fallible expression' <<< "$conditional_aborting_arm_keeps_reachable_family"
grep -q '^P 0$' <<< "$conditional_aborting_arm_keeps_reachable_family"

match_fallible_alias=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load() -> i64 error[E]:\n    return 1\ndef mismatch(flag: bool) -> i64 error[F]:\n    value = match flag:\n        true: load()\n        false: load()\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$match_fallible_alias"

match_fallible_block_alias=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load() -> i64 error[E]:\n    return 1\ndef mismatch(flag: bool) -> i64 error[F]:\n    value = match flag:\n        true:\n            copied = load()\n            copied\n        false: load()\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$match_fallible_block_alias"

block_expression_fallible_alias=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load() -> i64 error[E]:\n    return 1\ndef mismatch() -> i64 error[F]:\n    value =\n        copied = load()\n        copied\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$block_expression_fallible_alias"

fresh_guard_pattern_nonfallible=$(printf 'def bad(values: darray[i64]) -> i64:\n    result = item if values is [item] else 0\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$fresh_guard_pattern_nonfallible"

fallback_alias_nonfallible=$(printf 'error E:\n    Bad\ndef load() -> i64 error[E]:\n    return 1\ndef bad() -> i64:\n    result = try load() else 0\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$fallback_alias_nonfallible"

match_pattern_binder_shadows_family=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef mismatch(subject: i64, value: i64 error[E]) -> i64 error[F]:\n    copied = value\n    result = match subject:\n        copied: copied\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$match_pattern_binder_shadows_family"
! grep -q 'cannot propagate E from a function returning F' <<< "$match_pattern_binder_shadows_family"

match_guard_pattern_shadows_family=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef mismatch(subject: darray[i64], value: i64 error[E]) -> i64 error[F]:\n    copied = value\n    result = match subject:\n        _ if subject is [copied]: copied\n        _: 0\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$match_guard_pattern_shadows_family"
! grep -q 'cannot propagate E from a function returning F' <<< "$match_guard_pattern_shadows_family"

if_guard_pattern_shadows_family=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef mismatch(subject: darray[i64], value: i64 error[E]) -> i64 error[F]:\n    copied = value\n    result = copied if subject is [copied] else 0\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$if_guard_pattern_shadows_family"
! grep -q 'cannot propagate E from a function returning F' <<< "$if_guard_pattern_shadows_family"

parameter_rebinding=$(printf 'error E:\n    Bad\n\ndef forward(mutable value: i64 error[E]) -> i64 error[E]:\n    rebind value = value\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$parameter_rebinding"

parameter_scalar_rebinding=$(printf 'error E:\n    Bad\n\ndef bad(mutable value: i64 error[E]) -> i64 error[E]:\n    rebind value = 7\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$parameter_scalar_rebinding"

branch_parameter_scalar_rebinding=$(printf 'error E:\n    Bad\ndef forward(flag: bool, mutable value: i64 error[E]) -> i64 error[E]:\n    if flag:\n        rebind value = 7\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$branch_parameter_scalar_rebinding"

multi_target_rebinding=$(printf 'error E:\n    Bad\n\ndef forward(mutable other: i64, mutable value: i64 error[E]) -> i64 error[E]:\n    rebind other, value = 1, value\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$multi_target_rebinding"

same_line_parameter_families=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef mismatch(left: i64 error[E], right: i64 error[F]) -> i64 error[E]:\n    return try right\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$same_line_parameter_families"

multi_family_parameter_union=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef mismatch(value: i64 error[E, F]) -> i64 error[E]:\n    return try value\n' | "$RPT")
grep -q '^P 1$' <<< "$multi_family_parameter_union"
grep -q 'error-union value types currently support exactly one family' <<< "$multi_family_parameter_union"
! grep -q 'try requires a fallible expression' <<< "$multi_family_parameter_union"
! grep -q 'cannot propagate' <<< "$multi_family_parameter_union"

multi_target_fresh_family=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load_f() -> i64 error[F]:\n    return 1\ndef mismatch() -> i64 error[E]:\n    rebind first: i64, value: i64 = 1, load_f()\n    return try value\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$multi_target_fresh_family"

parallel_family_swap_snapshot=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load_e() -> i64 error[E]:\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef forward() -> i64 error[E]:\n    left = load_e()\n    right = load_f()\n    left, right = right, left\n    copied = right\n    return try copied\n' | "$RPT")
grep -q '^D 0$' <<< "$parallel_family_swap_snapshot"

local_error_union_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch() -> i64 error[E]:\n    wrapped: i64 error[F] = 7\n    return try wrapped\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$local_error_union_mismatch"

inferred_alias_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch(value: i64 error[E]) -> i64 error[F]:\n    alias = value\n    return try alias\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$inferred_alias_mismatch"

lambda_return_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef build(value: i64 error[E]) -> i64:\n    callback = fn() -> i64 error[F] => try value\n    return 0\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$lambda_return_mismatch"

lambda_numeric_shadow=$(printf 'error E:\n    Bad\ndef build() -> i64:\n    count: i64 = 1\n    callback = fn(count: i64 error[E]) -> i64 error[E] => try count\n    return 0\n' | "$RPT")
grep -q '^D 0$' <<< "$lambda_numeric_shadow"

lambda_without_error_destination=$(printf 'error E:\n    Bad\ndef maybe() -> i64 error[E]:\n    return 1\ndef build() -> i64 error[E]:\n    callback = fn() -> i64 => try maybe()\n    return 0\n' | "$RPT")
grep -q 'try without else requires an error union' <<< "$lambda_without_error_destination"

lambda_call_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef maybe() -> i64 error[E]:\n    return 1\ndef build() -> i64 error[E]:\n    callback = fn() -> i64 error[F] => try maybe()\n    return 0\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$lambda_call_mismatch"

reserved_lambda_context_name=$(printf 'error E:\n    Bad\ndef forward(__try_inside_lambda: i64 error[E]) -> i64 error[E]:\n    return try __try_inside_lambda\n' | "$RPT")
grep -q '^D 0$' <<< "$reserved_lambda_context_name"

scalar_local=$(printf 'def bad() -> i64:\n    value: i64 = 7\n    return try value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$scalar_local"

shadow_after_try=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    result: i64 = try value\n    if true:\n        value: i64 = 7\n    return result\n' | "$RPT")
grep -q '^D 0$' <<< "$shadow_after_try"

branch_shadow_does_not_escape=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef mismatch(flag: bool, value: i64 error[E]) -> i64 error[F]:\n    if flag:\n        value = 7\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$branch_shadow_does_not_escape"

pattern_shadow_does_not_escape_branch=$(printf 'def bad(subject: darray[i64]) -> i64:\n    value: i64 = 7\n    if subject is [value]:\n        pass\n    return try value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$pattern_shadow_does_not_escape_branch"

first_class_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch(value: i64 error[E]) -> i64 error[F]:\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$first_class_mismatch"

guard_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch(value: bool error[E]) -> int error[F]:\n    match true:\n        _ if try value:\n            return 0\n        _:\n            return 0\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$guard_mismatch"

assignment_target_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch(index: i64 error[E]) -> void error[F]:\n    values: mutable darray[i64] = [0]\n    values[try index] = 1\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$assignment_target_mismatch"

nonfallible_value=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> i64 error[E]:\n    return try 7\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_value"

nonfallible_unary=$(printf 'error E:\n    Bad\n\ndef bad() -> i64 error[E]:\n    return try -7\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_unary"

shadowed_value=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> i64 error[E]:\n    if true:\n        value: i64 = 7\n        return try value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$shadowed_value"

truthy_pattern_shadow=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> i64 error[E]:\n    if value is [value]:\n        return try value\n    return 0\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$truthy_pattern_shadow"

and_rhs_pattern_shadow=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> bool error[E]:\n    if value is [value] and try value:\n        return true\n    return false\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$and_rhs_pattern_shadow"

pattern_shadow_does_not_escape=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E], subject: darray[i64]) -> i64 error[E]:\n    wrapped: i64 error[E] = value\n    if subject is [wrapped]:\n        pass\n    return try wrapped\n' | "$RPT")
grep -q '^D 0$' <<< "$pattern_shadow_does_not_escape"

nonfallible_unary=$(printf 'def bad() -> i64:\n    return try -7\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_unary"

nonfallible_unary_plus=$(printf 'def bad() -> i64:\n    return try +7\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_unary_plus"

nonfallible_binary=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> i64 error[E]:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_binary"

nonfallible_usize_binary=$(printf 'def bad(value: usize) -> usize:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_usize_binary"

nonfallible_isize_binary=$(printf 'def bad(value: isize) -> isize:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_isize_binary"

nonfallible_conditional=$(printf 'def bad(flag: bool) -> i64:\n    return try (7 if flag else 8)\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_conditional"

recovered=$(printf 'def maybe(flag: bool) -> int?:\n    return 7 if flag else null\ndef ok(flag: bool) -> int:\n    return try maybe(flag) else 0\n' | "$RPT")
grep -q '^D 0$' <<< "$recovered"

bash "$REPO_ROOT/test/parity/try_lexical_lookup_smoke.sh"
bash "$REPO_ROOT/test/parity/try_error_subset_coverage_smoke.sh"
bash "$REPO_ROOT/test/parity/try_error_malformed_empty_destination_different_source_smoke.sh"
bash "$REPO_ROOT/test/parity/try_overload_error_set_by_argument_type_smoke.sh"
bash "$REPO_ROOT/test/parity/try_overload_error_set_by_struct_argument_smoke.sh"
bash "$REPO_ROOT/test/parity/try_error_repeated_family_subsets_smoke.sh"
bash "$REPO_ROOT/test/parity/try_error_dot_subset_smoke.sh"
bash "$REPO_ROOT/test/parity/try_error_bare_variant_subset_smoke.sh"

