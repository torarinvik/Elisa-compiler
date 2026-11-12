#!/usr/bin/env bash
# The Python boundary's opaque type must survive semantic analysis in nested
# containers and fields, without making the unrelated bare name Object legal.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

for fixture in optional_object nullable_lists nullable_dicts views object_list struct_views; do
    output="$("$RPT" < "$REPO_ROOT/test/repro/pymodule_${fixture}.elisa")"
    [[ "$output" == *$'P 0\nD 0'* ]] || {
        printf 'Python object semantic smoke failed for %s:\n%s\n' "$fixture" "$output" >&2
        exit 1
    }
done

output="$(printf 'def bad(value: Object) -> Object:\n    return value\n' | "$RPT")"
[[ "$output" == *'unknown type "Object"'* ]] || {
    printf 'bare Object was accepted:\n%s\n' "$output" >&2
    exit 1
}
echo 'Python object semantic smoke OK'
