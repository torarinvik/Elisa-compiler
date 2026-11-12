#!/usr/bin/env bash
# Comparing a bare global address does not read it through a competing alias.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/global_address_identity.elisa"
report="$("$RPT" < "$fixture")"
if grep -q 'while the caller lends' <<< "$report"; then
    printf 'address identity was treated as a global read:\n%s\n' "$report" >&2
    exit 1
fi
read_report="$(sed '/note(b) if b == &well_known/a\
        note(b) if well_known.n > 0' "$fixture" | "$RPT")"
grep -q 'reads global "well_known" while the caller lends' <<< "$read_report" || {
    printf 'actual global read was not rejected:\n%s\n' "$read_report" >&2
    exit 1
}
echo 'global address identity smoke OK'
