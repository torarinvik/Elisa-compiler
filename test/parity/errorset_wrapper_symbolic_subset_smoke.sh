#!/usr/bin/env bash
# A polymorphic wrapper must retain the callback's exact error subset.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

output="$("$RPT" < "$REPO_ROOT/test/repro/errorset_wrapper_symbolic_subset.elisa")"
[[ "$output" == *$'P 0\nD 1\n'* && "$output" == *'L18 return type expects error[Fault], got an incompatible error set also named Fault'* ]] || {
    printf 'symbolic error-set subset check failed:\n%s\n' "$output" >&2
    exit 1
}
echo 'symbolic error-set subset smoke OK'
