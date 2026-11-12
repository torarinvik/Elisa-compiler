#!/usr/bin/env bash
# A callback's symbolic errorset can propagate to the same parameter, but not
# to an independent parameter of the enclosing function.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

output="$("$RPT" <<'ELISA'
def forward[errorset R](callback: fn() -> i64 error[R]) -> i64 error[R]:
    return try callback()

def mismatch[errorset R, errorset S](callback: fn() -> i64 error[R]) -> i64 error[S]:
    return try callback()
ELISA
)"
[[ "$output" == *$'P 0\nD 1\n'* && "$output" == *'L5 cannot propagate R from a function returning S'* ]] || {
    printf 'errorset parameter forwarding failed:\n%s\n' "$output" >&2
    exit 1
}
echo 'errorset parameter forwarding smoke OK'
