#!/usr/bin/env bash
# A bare error variant names its unique family and restricts it to that tag.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/backend_bare_error_variant_subset.elisa"
allowed="$("$RPT" < "$fixture")"
if grep -q 'raise cannot propagate' <<< "$allowed"; then
    printf 'matching bare variant was rejected:\n%s\n' "$allowed" >&2
    exit 1
fi
wrong="$(sed 's/raise Fault.Expected if fail/raise Fault.Other if fail/' "$fixture" | "$RPT")"
grep -q 'raise cannot propagate tag "Fault.Other".*Fault.Expected' <<< "$wrong" || {
    printf 'different variant was not rejected:\n%s\n' "$wrong" >&2
    exit 1
}
echo 'bare error variant raise subset smoke OK'
