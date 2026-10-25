#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

report=$("$RPT" < "$ROOT/test/repro/catch_global_nested_alias.elisa")
grep -q '^D 2$' <<< "$report"
missing_count="$(grep -c 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$report" || true)"
[[ "$missing_count" == 2 ]] || {
    printf 'global nested-alias Catch smoke expected both alias paths to select AliasHome::Provider::Fault:\n%s\n' "$report" >&2
    exit 1
}

echo "global nested-alias Catch smoke OK"

chain_report=$("$RPT" < "$ROOT/test/repro/catch_global_alias_head_later.elisa")
grep -q '^D 2$' <<< "$chain_report"
chain_missing_count="$(grep -c 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$chain_report" || true)"
[[ "$chain_missing_count" == 2 ]] || {
    printf 'global alias-head Catch smoke expected later parent alias registration to resolve both catch paths:\n%s\n' "$chain_report" >&2
    exit 1
}

echo "global alias-head Catch smoke OK"
