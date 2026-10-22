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

shadow_after_try=$(printf 'error E:\n    Bad\n\ndef forward(value: i64 error[E]) -> i64 error[E]:\n    result: i64 = try value\n    if true:\n        value: i64 = 7\n    return result\n' | "$RPT")
grep -q '^D 0$' <<< "$shadow_after_try"

first_class_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch(value: i64 error[E]) -> i64 error[F]:\n    return try value\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$first_class_mismatch"

guard_mismatch=$(printf 'error E:\n    Bad\n\nerror F:\n    Other\n\ndef mismatch(value: bool error[E]) -> int error[F]:\n    match true:\n        _ if try value:\n            return 0\n        _:\n            return 0\n' | "$RPT")
grep -q 'cannot propagate E from a function returning F' <<< "$guard_mismatch"

nonfallible_value=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> i64 error[E]:\n    return try 7\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$nonfallible_value"

shadowed_value=$(printf 'error E:\n    Bad\n\ndef bad(value: i64 error[E]) -> i64 error[E]:\n    if true:\n        value: i64 = 7\n        return try value\n' | "$RPT")
grep -q 'try requires a fallible expression' <<< "$shadowed_value"

recovered=$(printf 'def maybe(flag: bool) -> int?:\n    return 7 if flag else null\ndef ok(flag: bool) -> int:\n    return try maybe(flag) else 0\n' | "$RPT")
grep -q '^D 0$' <<< "$recovered"

echo "try fallibility smoke OK" >&2
