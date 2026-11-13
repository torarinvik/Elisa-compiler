#!/usr/bin/env bash
# Scalar block results are local; reference results keep their global origin.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
for fixture in block_expression_scope block_expression_diverging; do
    out="$("$RPT" < "$REPO_ROOT/test/differential/cases/$fixture.elisa")"
    grep -Fxq 'P 0' <<< "$out" && grep -Fxq 'D 0' <<< "$out" || {
        printf '%s failed:\n%s\n' "$fixture" "$out" >&2
        exit 1
    }
done
for case_name in read write choice diverging; do
    out="$("$RPT" < "$REPO_ROOT/test/repro/block_global_${case_name}_authority.elisa")"
    required=Global.Read
    [[ "$case_name" != write ]] || required=Global.Write
    grep -q '^P 0$' <<< "$out" && grep -Fq "without $required" <<< "$out" || {
        printf 'global %s block was not diagnosed:\n%s\n' "$case_name" "$out" >&2
        exit 1
    }
done
echo 'block global authority smoke OK'
