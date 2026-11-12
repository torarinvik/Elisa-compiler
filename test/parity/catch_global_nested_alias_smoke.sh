#!/usr/bin/env bash
# A nested alias is unavailable to catches and type references at root.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"
for fixture in catch_global_nested_alias catch_global_alias_head_later; do
    report="$("$RPT" < "$ROOT/test/repro/$fixture.elisa")"
    grep -q '^D 1$' <<< "$report" || { printf '%s: unexpected diagnostics:\n%s\n' "$fixture" "$report" >&2; exit 1; }
    grep -q 'undefined identifier' <<< "$report" || { printf '%s: missing undefined alias diagnostic:\n%s\n' "$fixture" "$report" >&2; exit 1; }
    if grep -q 'non-exhaustive catch' <<< "$report"; then
        printf '%s: inferred a family through an out-of-scope alias:\n%s\n' "$fixture" "$report" >&2
        exit 1
    fi
done
echo 'nested alias catch scope smoke OK'
