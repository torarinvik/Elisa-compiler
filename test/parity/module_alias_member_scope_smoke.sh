#!/usr/bin/env bash
# A chained alias resolves its target's members only in its declaring scope.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

output="$("$RPT" <<'ELISA'
module Outer:
    public:
        module Nested:
            public:
                def good() -> i64:
                    return 1
module Client:
    using Outer as Root
    using Root::Nested as Alias
    def good() -> i64:
        return Alias::good()
    def bad() -> i64:
        return Alias::missing()
def outside() -> i64:
    return Alias::good()
ELISA
)"
[[ "$output" == *$'P 0\nD 2\n'* && "$output" == *'L13 undefined identifier "Alias.missing"'* && "$output" == *'L15 undefined identifier "Alias.good"'* ]] || {
    printf 'module alias member scope failed:\n%s\n' "$output" >&2
    exit 1
}
echo 'module alias member scope smoke OK'
