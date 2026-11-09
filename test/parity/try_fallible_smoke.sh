#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_try_variant_alias_owner_identity.py"
python3 "$REPO_ROOT/test/proofs/check_codegen_variant_alias_owner_identity.py"

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

first_class_ambiguous_family=$(cat "$REPO_ROOT/test/repro/try_first_class_ambiguous_error_family.elisa" | "$RPT")
grep -q '^D 1$' <<< "$first_class_ambiguous_family" && grep -q 'cannot propagate Fault from a function returning Fault' <<< "$first_class_ambiguous_family" || {
    echo "try_fallible FAILED: a first-class Fault from duplicate modules was accepted by a line-zero caller returning Provider::Fault: $first_class_ambiguous_family"
    exit 1
}

first_class_inactive_duplicate_family=$(cat "$REPO_ROOT/test/repro/try_first_class_inactive_duplicate_error_family.elisa" | "$RPT")
grep -q '^D 0$' <<< "$first_class_inactive_duplicate_family" || {
    echo "try_fallible FAILED: an inactive duplicate ErrorSet made a unique active Provider::Fault ambiguous: $first_class_inactive_duplicate_family"
    exit 1
}

line_zero_nonerror=$(cat "$REPO_ROOT/test/repro/try_nonerror_enclosing_line_zero.elisa" | "$RPT")
grep -q 'try without else requires the current function to return an error union' <<< "$line_zero_nonerror" || {
    echo "try_fallible FAILED: a #line 0 non-error caller did not receive the required error-union diagnostic: $line_zero_nonerror"
    exit 1
}

variant_alias_owner=$(cat "$REPO_ROOT/test/repro/try_variant_alias_owner_line_zero.elisa" | "$RPT")
variant_alias_owner_count=$(grep -Fc 'cannot propagate OriginFault from a function returning CallerFault' <<< "$variant_alias_owner" || true)
if [[ "$variant_alias_owner_count" -ne 1 ]]; then
    echo "try_fallible FAILED: a same-line sibling variant target shadowed the outer fallible payload: $variant_alias_owner"
    exit 1
fi

callback_return_occurrence='error CallbackFault:
    Bad
error ReturnFault:
    Other

def bad(callback: fn() -> i64 error[CallbackFault]) -> i64 error[ReturnFault]:
    return try callback()

def good(callback: fn() -> i64 error[CallbackFault]) -> i64 error[CallbackFault]:
    return try callback()'
callback_return_occurrence_report=$(printf '%s\n' "$callback_return_occurrence" | "$RPT")
grep -q '^D 1$' <<< "$callback_return_occurrence_report" || {
    echo "try_fallible FAILED: expected exactly the incompatible callback/return diagnostic: $callback_return_occurrence_report"
    exit 1
}
grep -q 'cannot propagate CallbackFault from a function returning ReturnFault' <<< "$callback_return_occurrence_report" || {
    echo "try_fallible FAILED: callback parameter error set was mistaken for the enclosing return set: $callback_return_occurrence_report"
    exit 1
}
[[ $(grep -c 'cannot propagate CallbackFault from a function returning ReturnFault' <<< "$callback_return_occurrence_report") -eq 1 ]] || {
    echo "try_fallible FAILED: expected exactly one callback/return occurrence mismatch: $callback_return_occurrence_report"
    exit 1
}

composite_source='error Foo:
    FooTag
error Bar:
    BarTag

def may_fail() -> i64 error[Foo, Bar]:
    return 1

def only_foo() -> i64 error[Foo]:
    return try may_fail()'
composite_source_report=$(printf '%s\n' "$composite_source" | "$RPT")
grep -q '^D 1$' <<< "$composite_source_report" || {
    echo "try_fallible FAILED: expected composite source to reject its unrepresented Bar family: $composite_source_report"
    exit 1
}
grep -q 'cannot propagate Bar from a function returning Foo' <<< "$composite_source_report" || {
    echo "try_fallible FAILED: composite source was accepted by a caller that only returns Foo: $composite_source_report"
    exit 1
}
[[ $(grep -c 'cannot propagate Bar from a function returning Foo' <<< "$composite_source_report") -eq 1 ]] || {
    echo "try_fallible FAILED: expected exactly one diagnostic for the unrepresented Bar family: $composite_source_report"
    exit 1
}

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
qualified_leaf_collision_report=$(cat "$REPO_ROOT/test/repro/try_qualified_module_leaf_collision.elisa" | "$RPT")
grep -q '^D 1$' <<< "$qualified_leaf_collision_report" && grep -q 'cannot propagate E from a function returning F' <<< "$qualified_leaf_collision_report" || {
    echo "try_fallible FAILED: Common::fail matched the duplicate-leaf OuterB module instead of lexical OuterA::Common: $qualified_leaf_collision_report"
    exit 1
}

zero_offset_enclosing_identity_report=$(cat "$REPO_ROOT/test/repro/try_zero_offset_enclosing_function_identity.elisa" | "$RPT")
grep -q '^D 0$' <<< "$zero_offset_enclosing_identity_report" || {
    echo "try_fallible FAILED: a same-#line sibling displaced the byte-zero caller of try load(): $zero_offset_enclosing_identity_report"
    exit 1
}

nested_global_alias_report=$(cat "$REPO_ROOT/test/repro/try_nested_global_using_alias.elisa" | "$RPT")
grep -q '^D 0$' <<< "$nested_global_alias_report" || {
    echo "try_fallible FAILED: root call could not resolve a module alias declared in a nested module: $nested_global_alias_report"
    exit 1
}

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

source "$REPO_ROOT/test/parity/try_fallible_catch_cases.sh"

echo "try fallibility smoke OK" >&2
