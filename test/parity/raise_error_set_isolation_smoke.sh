#!/usr/bin/env bash
# A later function's subset must not constrain an earlier unrestricted return.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

output="$("$RPT" <<'ELISA'
module Api:
    error Fault:
        Available
        Busy

    def unrestricted() -> i64 error[Api::Fault]:
        raise Api::Fault.Available

    def restricted() -> i64 error[Api::Fault{Busy}]:
        raise Api::Fault.Available
ELISA
)"
[[ "$output" == *$'P 0\nD 1\n'* && "$output" == *'L10 raise cannot propagate tag "Fault.Available" into error[Fault.Busy]'* ]] || {
    printf 'raise error-set isolation failed:\n%s\n' "$output" >&2
    exit 1
}
echo 'raise error-set isolation smoke OK'
