#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

case_source='error E:
    Bad
error F:
    Other
module Backend:
    public:
        def load() -> i64 error[E]:
            return 1
module Importer:
    public:
        using Backend
        def imported() -> i64 error[E]:
            copied = load()
            return try copied
module Sibling:
    public:
        def unimported() -> i64 error[F]:
            copied = load()
            return try copied'
report=$(printf '%s\n' "$case_source" | "$RPT")

[[ $(grep -c 'try requires a fallible expression' <<< "$report") -eq 1 ]] || {
    echo "try wildcard import scope FAILED: nested import leaked into or disappeared from the wrong module: $report"
    exit 1
}
! grep -q 'cannot propagate E from a function returning F' <<< "$report" || {
    echo "try wildcard import scope FAILED: sibling inherited another module's import: $report"
    exit 1
}

echo "try wildcard import scope OK"
