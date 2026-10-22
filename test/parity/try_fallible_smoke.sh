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

parameter_rebinding=$(printf 'error E:\n    Bad\n\ndef forward(mutable value: i64 error[E]) -> i64 error[E]:\n    rebind value = value\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$parameter_rebinding"

parameter_scalar_rebinding=$(printf 'error E:\n    Bad\n\ndef bad(mutable value: i64 error[E]) -> i64 error[E]:\n    rebind value = 7\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$parameter_scalar_rebinding"

multi_target_rebinding=$(printf 'error E:\n    Bad\n\ndef forward(mutable other: i64, mutable value: i64 error[E]) -> i64 error[E]:\n    rebind other, value = 1, value\n    return try value\n' | "$RPT")
grep -q '^D 0$' <<< "$multi_target_rebinding"

multi_target_fresh_family=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef load_f() -> i64 error[F]:\n    return 1\ndef mismatch() -> i64 error[E]:\n    rebind first: i64, value: i64 = 1, load_f()\n    return try value\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$multi_target_fresh_family"

local_error_union_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch() -> i64 error[E]:\n    wrapped: i64 error[F] = 7\n    return try wrapped\n' | "$RPT")
grep -q 'cannot propagate F from a function returning E' <<< "$local_error_union_mismatch"

inferred_alias_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch(value: i64 error[E]) -> i64 error[F]:\n    alias = value\n    return try alias\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$inferred_alias_mismatch"

lambda_return_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef build(value: i64 error[E]) -> i64:\n    callback = fn() -> i64 error[F] => try value\n    return 0\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$lambda_return_mismatch"

lambda_without_error_destination=$(printf 'error E:\n    Bad\ndef maybe() -> i64 error[E]:\n    return 1\ndef build() -> i64 error[E]:\n    callback = fn() -> i64 => try maybe()\n    return 0\n' | "$RPT")
grep -q 'try without else requires an error union' <<< "$lambda_without_error_destination"

lambda_call_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\ndef maybe() -> i64 error[E]:\n    return 1\ndef build() -> i64 error[E]:\n    callback = fn() -> i64 error[F] => try maybe()\n    return 0\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$lambda_call_mismatch"

scalar_local=$(printf 'def bad() -> i64:\n    value: i64 = 7\n    return try value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$scalar_local"

shadow_after_try=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    result: i64 = try value\n    if true:\n        value: i64 = 7\n    return result\n' | "$RPT")
grep -q '^D 0$' <<< "$shadow_after_try"

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

nonfallible_binary=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> i64 error[E]:\n    return try value + 1\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_binary"

recovered=$(printf 'def maybe(flag: bool) -> int?:\n    return 7 if flag else null\ndef ok(flag: bool) -> int:\n    return try maybe(flag) else 0\n' | "$RPT")
grep -q '^D 0$' <<< "$recovered"

echo "try fallibility smoke OK" >&2
