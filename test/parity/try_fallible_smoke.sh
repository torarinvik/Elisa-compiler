#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

optional=$(printf 'def maybe(flag: bool) -> int?:\n    return 7 if flag else null\ndef bad(flag: bool) -> int:\n    return try maybe(flag)\n' | "$RPT")
grep -q 'try without else requires an error union' <<< "$optional"

scalar=$(printf 'def bad() -> int:\n    value: int = try 7\n    return value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$scalar"

unary_numeric_parameter=$(printf 'def bad(value: i64) -> i64:\n    return try +value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$unary_numeric_parameter"

nested_numeric_expression=$(printf 'def bad(left: i64, right: i64) -> i64:\n    return try (left + right) * 2\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nested_numeric_expression"

numeric_alias_parameter=$(printf 'type Count = i64\ndef bad(value: Count) -> i64:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$numeric_alias_parameter"

chained_numeric_alias_parameter=$(printf 'type Count = i64\ntype SmallCount = Count\ndef bad(value: SmallCount) -> i64:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$chained_numeric_alias_parameter"

module_scoped_numeric_alias_collision='module Alpha:
    type Count = i64
    def bad(value: Count) -> i64:
        return try value + 1
module Beta:
    type Count = string'
module_scoped_numeric_alias_report=$(printf '%s\n' "$module_scoped_numeric_alias_collision" | "$RPT")
grep -q 'try requires a fallible expression' <<< "$module_scoped_numeric_alias_report" || {
    echo "try_fallible FAILED: sibling-module alias shadowed a visible numeric alias: $module_scoped_numeric_alias_report"
    exit 1
}

numeric_alias_local=$(printf 'type Count = i64\ndef bad() -> i64:\n    value: Count = 1\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$numeric_alias_local"

typed_local_chained_numeric=$(printf 'def bad() -> i64:\n    value: i64 = 2\n    return try (value + 3) * 7\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$typed_local_chained_numeric"

local_numeric_binary_alias=$(printf 'def bad() -> i64:\n    x: i64 = 1\n    return try x + 1 else 0\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$local_numeric_binary_alias"

nonfallible_int_binary=$(printf 'def bad(value: int) -> int:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_int_binary"

nonfallible_u8_binary=$(printf 'def bad(value: u8) -> u8:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_u8_binary"

nonfallible_u64_binary=$(printf 'def bad(value: u64) -> u64:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_u64_binary"

nonfallible_usize_binary=$(printf 'def bad(value: usize) -> usize:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_usize_binary"

nonfallible_f32_binary=$(printf 'def bad(value: f32) -> f32:\n    return try value + 1.0\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_f32_binary"

nonfallible_f64_binary=$(printf 'def bad(value: f64) -> f64:\n    return try value + 1.0\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_f64_binary"

nonfallible_char_binary=$(printf "def bad(value: char) -> i64:\n    return try value - 'a'\n" | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_char_binary"

nonfallible_integer_bitwise=$(printf 'def bad(left: i64, right: i64) -> i64:\n    return try left & right\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_integer_bitwise"

nonfallible_integer_shift_alias=$(printf 'def bad(left: i64) -> i64:\n    copied = left\n    return try copied << 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_integer_shift_alias"

nonfallible_local_integer_shift=$(printf 'def bad() -> i64:\n    value: i64 = 3\n    return try value << 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_local_integer_shift"

nonfallible_uintptr_binary=$(printf 'def bad(value: uintptr) -> uintptr:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_uintptr_binary"

unary_numeric_alias=$(printf 'def bad(value: i64) -> i64:\n    result = -(value + 1)\n    return try result\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$unary_numeric_alias"

first_class=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$first_class"

nested_parens=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    return try ((value))\n' | "$RPT")
grep -q '^D 0$' <<< "$nested_parens"

nested_call_argument=$(printf 'error E:\n    Bad\n\ndef keep(value: i64) -> i64:\n    return value\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    return keep(try value)\n' | "$RPT")
grep -q '^D 0$' <<< "$nested_call_argument"

assignment_target=$(printf 'error E:\n    Bad\n\ndef forward(index: i64 error[E]) -> void error[E]:\n    values: mutable darray[i64] = [0]\n    values[try index] = 1\n' | "$RPT")
grep -q '^D 0$' <<< "$assignment_target"

nested_call=$(printf 'error E:\n    Bad\ndef identity(value: i64) -> i64:\n    return value\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    return identity(try value)\n' | "$RPT")
grep -q '^D 0$' <<< "$nested_call"

nested_tuple=$(printf 'error E:\n    Bad\ndef identity(value: i64) -> i64:\n    return value\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    pair = (identity(try value), 1)\n    return 0\n' | "$RPT")
grep -q '^D 0$' <<< "$nested_tuple"

local_error_union=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    wrapped: i64 error[E] = value\n    return try wrapped\n' | "$RPT")
grep -q '^D 0$' <<< "$local_error_union"

parameter_alias_rebinding=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    wrapped = value\n    return try wrapped\n' | "$RPT")
grep -q '^D 0$' <<< "$parameter_alias_rebinding"

parameter_alias_chain=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    first = value\n    wrapped = first\n    return try wrapped\n' | "$RPT")
grep -q '^D 0$' <<< "$parameter_alias_chain"

local_error_union_alias=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    wrapped: i64 error[E] = value\n    copied = wrapped\n    return try copied\n' | "$RPT")
grep -q '^D 0$' <<< "$local_error_union_alias"

fallible_call_alias=$(printf 'error E:\n    Bad\n\ndef load() -> i64 error[E]:\n    return 1\n\ndef forward() -> i64 error[E]:\n    copied = load()\n    return try copied\n' | "$RPT")
grep -q '^D 0$' <<< "$fallible_call_alias"

pure_call_alias_nonfallible=$(printf 'def pure() -> i64:\n    return 1\ndef bad() -> i64:\n    value = pure()\n    return try value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$pure_call_alias_nonfallible"

unqualified_sibling_module_callable='error E:
    Bad
module Alpha:
    public:
        def pure() -> i64:
            return 1
        def bad() -> i64:
            value = pure()
            return try value
module Beta:
    public:
        def pure() -> i64 error[E]:
            return 2'
unqualified_sibling_module_callable_report=$(printf '%s\n' "$unqualified_sibling_module_callable" | "$RPT")
grep -q 'try requires a fallible expression' <<< "$unqualified_sibling_module_callable_report" || {
    echo "try_fallible FAILED: unqualified Alpha::pure resolved to its fallible Beta sibling: $unqualified_sibling_module_callable_report"
    exit 1
}

imported_callable_fact_sources='error E:
    Bad
error F:
    Other
module Backend:
    public:
        def load() -> i64 error[E]:
            return 1
module Selective:
    public:
        using Backend::load
        def mismatch() -> i64 error[F]:
            copied = load()
            return try copied
module Wildcard:
    public:
        using Backend
        def mismatch() -> i64 error[F]:
            copied = load()
            return try copied'
imported_callable_fact_sources_report=$(printf '%s\n' "$imported_callable_fact_sources" | "$RPT")
[[ $(grep -c 'cannot propagate E from a function returning F' <<< "$imported_callable_fact_sources_report") -eq 2 ]] || {
    echo "try_fallible FAILED: unqualified calls through selective or wildcard imports lost their error family: $imported_callable_fact_sources_report"
    exit 1
}

nested_wildcard_callable_sources='error E:
    Bad
error F:
    Other
module BackendE:
    public:
        def load() -> i64 error[E]:
            return 1
module BackendF:
    public:
        def load() -> i64 error[F]:
            return 2
module Alpha:
    public:
        using BackendE
        def mismatch() -> i64 error[F]:
            copied = load()
            return try copied
module Beta:
    public:
        using BackendF
        def mismatch() -> i64 error[E]:
            copied = load()
            return try copied'
nested_wildcard_callable_sources_report=$(printf '%s\n' "$nested_wildcard_callable_sources" | "$RPT")
[[ $(grep -c 'cannot propagate E from a function returning F' <<< "$nested_wildcard_callable_sources_report") -eq 1 && $(grep -c 'cannot propagate F from a function returning E' <<< "$nested_wildcard_callable_sources_report") -eq 1 ]] || {
    echo "try_fallible FAILED: sibling wildcard imports did not retain their lexical module scopes: $nested_wildcard_callable_sources_report"
    exit 1
}
grep -q '^P 0$' <<< "$nested_wildcard_callable_sources_report"

alias_only_using_does_not_import_unqualified_callable=$(printf 'error E:\n    Bad\nerror F:\n    Other\nmodule Backend:\n    public:\n        def load() -> i64 error[E]:\n            return 1\nusing Backend as B\ndef mismatch() -> i64 error[F]:\n    copied = load()\n    return try copied\n' | "$RPT")
! grep -q 'cannot propagate E from a function returning F' <<< "$alias_only_using_does_not_import_unqualified_callable"

qualified_pure_call_alias_nonfallible=$(printf 'error E:\n    Bad\nmodule Backend:\n    public:\n        def pure() -> i64:\n            return 1\nmodule Other:\n    public:\n        def pure() -> i64 error[E]:\n            return 2\ndef bad() -> i64:\n    value = Backend::pure()\n    return try value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$qualified_pure_call_alias_nonfallible"

nested_qualified_module_declarations='error E:
    Bad
module OuterA:
    public:
        module Common:
            public:
                def pure() -> i64:
                    return 1
module OuterB:
    public:
        module Common:
            public:
                def pure() -> i64 error[E]:
                    return 2'
nested_qualified_pure_call_alias_nonfallible=$(printf '%s\ndef bad() -> i64:\n    value = OuterA::Common::pure()\n    return try value\n' "$nested_qualified_module_declarations" | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nested_qualified_pure_call_alias_nonfallible"
nested_qualified_pure_direct_try_nonfallible=$(printf '%s\ndef bad() -> i64:\n    return try OuterA::Common::pure()\n' "$nested_qualified_module_declarations" | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nested_qualified_pure_direct_try_nonfallible"
nested_qualified_pure_direct_try_fallible=$(printf '%s\ndef good() -> i64 error[E]:\n    return try OuterB::Common::pure()\n' "$nested_qualified_module_declarations" | "$RPT")
grep -q '^D 0$' <<< "$nested_qualified_pure_direct_try_fallible" || {
    echo "try_fallible FAILED: direct try through OuterB::Common lost its error family: $nested_qualified_pure_direct_try_fallible"
    exit 1
}
nested_qualified_pure_call_alias_fallible=$(printf '%s\ndef good() -> i64:\n    value = OuterB::Common::pure()\n    return try value\n' "$nested_qualified_module_declarations" | "$RPT")
if grep -q 'try requires a fallible expression' <<< "$nested_qualified_pure_call_alias_fallible"; then
    echo "try_fallible FAILED: fallible OuterB::Common::pure was classified as nonfallible"
    exit 1
fi
using_alias_declarations='error E:
    Bad
module Backend:
    public:
        def load() -> i64 error[E]:
            return 1
using Backend as B'
using_alias_direct=$(printf '%s\ndef forward() -> i64 error[E]:\n    return try B::load()\n' "$using_alias_declarations" | "$RPT")
grep -q '^D 0$' <<< "$using_alias_direct" || {
    echo "try_fallible FAILED: direct try through using alias lost its error family: $using_alias_direct"
    exit 1
}
using_alias_assignment=$(printf '%s\ndef forward() -> i64 error[E]:\n    copied = B::load()\n    return try copied\n' "$using_alias_declarations" | "$RPT")
grep -q '^D 0$' <<< "$using_alias_assignment" || {
    echo "try_fallible FAILED: assigned call through using alias lost its error family: $using_alias_assignment"
    exit 1
}

using_alias_prefix_declarations='error E:
    Bad
module Outer:
    public:
        module Inner:
            public:
                def load() -> i64 error[E]:
                    return 1
using Outer as O'
using_alias_prefix_catch=$(printf '%s\ndef bad() -> i64:\n    result = catch O::Inner::load():\n        success: success\n        error problem: 0\n    return try result\n' "$using_alias_prefix_declarations" | "$RPT")
grep -q 'try requires a fallible expression' <<< "$using_alias_prefix_catch" || {
    echo "try_fallible FAILED: alias prefix O::Inner did not resolve the cached callable: $using_alias_prefix_catch"
    exit 1
}

root_using_alias_nested_module='error E:
    Bad
module Backend:
    public:
        def load() -> i64 error[E]:
            return 1
using Backend as RootB
module Outer:
    module Worker:
        def direct() -> i64 error[E]:
            return try RootB::load()
        def assigned() -> i64 error[E]:
            copied = RootB::load()
            return try copied'
root_using_alias_nested_report=$(printf '%s\n' "$root_using_alias_nested_module" | "$RPT")
grep -q '^D 0$' <<< "$root_using_alias_nested_report" || {
    echo "try_fallible FAILED: nested module could not resolve root using alias on direct and assigned calls: $root_using_alias_nested_report"
    exit 1
}

nested_same_leaf_aliases='module OuterA:
    module Common:
        type Count = i64
        def bad(value: Count) -> i64:
            return try value
module OuterB:
    module Common:
        type Count = string
        def bad(value: Count) -> i64:
            return try value'
nested_same_leaf_aliases_report=$(printf '%s\n' "$nested_same_leaf_aliases" | "$RPT")
[[ $(grep -c 'try requires a fallible expression' <<< "$nested_same_leaf_aliases_report") -eq 2 ]] || {
    echo "try_fallible FAILED: nested same-leaf type aliases collided: $nested_same_leaf_aliases_report"
    exit 1
}

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

# The inner Catch can raise only on the declared-fallible call's error path. The outer
# Catch recovers that path, so its returning error arm must remain in the conditional's
# source facts and expose load_f's F family to the final Try.
nested_catch_recovery_branch_keeps_fallible_family=$(printf 'error E:\n    Bad\nerror F:\n    Other\ndef load_e(flag: bool) -> i64 error[E]:\n    raise E.Bad if flag\n    return 1\ndef load_f() -> i64 error[F]:\n    return 2\ndef bad(flag: bool) -> i64 error[E] can[Abort.Panic]:\n    value = (catch (catch load_e(flag):\n        success:\n            panic()\n        error problem:\n            raise F.Other\n    ):\n        success:\n            0\n        error problem:\n            load_f()\n    ) if flag else 0\n    return try value\n' | "$RPT")
grep -q '^P 0$' <<< "$nested_catch_recovery_branch_keeps_fallible_family" || {
    echo "try_fallible FAILED: nested Catch recovery fixture did not parse: $nested_catch_recovery_branch_keeps_fallible_family"
    exit 1
}
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

echo "try fallibility smoke OK" >&2
