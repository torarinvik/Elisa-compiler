#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
out="$("$RPT" < "$REPO_ROOT/test/repro/affine_region_binding_identity.elisa")"
grep -q '^P 0$' <<< "$out"
grep -Fq 'linear value "differing_ticket" must be consumed before scope exit' <<< "$out"
if grep -Fq 'linear value "matching_ticket" must be consumed before scope exit' <<< "$out"; then
    echo "affine region binding identity: same-region argument lost its consuming postcondition" >&2
    exit 1
fi
if grep -Fq 'linear value "nominal_ticket" must be consumed before scope exit' <<< "$out"; then
    echo "affine region binding identity: out-of-scope region name hid a nominal type" >&2
    exit 1
fi
echo 'affine region binding identity OK'
