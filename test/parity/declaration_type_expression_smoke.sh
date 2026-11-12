#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

for program in \
    $'def f() -> 4:\n    pass\n' \
    $'def f() -> -4:\n    pass\n' \
    $'def f() -> i64 + 1:\n    pass\n' \
    $'def f(x: 4) -> void:\n    pass\n' \
    $'struct Bad:\n    field: 4\n' \
    $'def f() -> void:\n    value: 4 = 1\n'; do
    report="$("$RPT" <<< "$program")"
    if grep -Fxq 'P 0' <<< "$report"; then
        printf 'invalid declared type accepted:\n%s\n%s\n' "$program" "$report" >&2
        exit 1
    fi
done

minus="$(printf 'def f() -> -4:\n    pass\n' | "$RPT")"
grep -Fq 'expected IDENT, got -' <<< "$minus" || { printf 'wrong unary type diagnostic:\n%s\n' "$minus" >&2; exit 1; }
arithmetic="$(printf 'def f() -> i64 + 1:\n    pass\n' | "$RPT")"
grep -Fq 'expected :, got +' <<< "$arithmetic" || { printf 'wrong arithmetic type diagnostic:\n%s\n' "$arithmetic" >&2; exit 1; }
parameter="$(printf 'def f(x: i64 + 1) -> void:\n    pass\n' | "$RPT")"
grep -Fq 'expected ), got +' <<< "$parameter" || { printf 'wrong parameter type diagnostic:\n%s\n' "$parameter" >&2; exit 1; }
field="$(printf 'struct S:\n    value: i64 + 1\n' | "$RPT")"
grep -Fq 'expected newline, got +' <<< "$field" || { printf 'wrong field type diagnostic:\n%s\n' "$field" >&2; exit 1; }

valid="$(printf 'def f(values: i64[4]) -> i64:\n    return values[0]\n' | "$RPT")"
if ! grep -Fxq 'P 0' <<< "$valid"; then
    printf 'array type with numeric extent rejected:\n%s\n' "$valid" >&2
    exit 1
fi
printf 'declaration type expressions reject values and preserve extents\n'
