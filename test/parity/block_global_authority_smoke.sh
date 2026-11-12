#!/usr/bin/env bash
# Scalar block results are local; reference results keep their global origin.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
out="$("$RPT" < "$REPO_ROOT/test/differential/cases/block_expression_scope.elisa")"
grep -q '^P 0$' <<< "$out" && grep -q '^D 0$' <<< "$out" || { printf 'scalar block failed:\n%s\n' "$out" >&2; exit 1; }
for case_name in read write choice; do
    out="$("$RPT" < "$REPO_ROOT/test/repro/block_global_${case_name}_authority.elisa")"
    required=Global.Read
    [[ "$case_name" != write ]] || required=Global.Write
    grep -q '^P 0$' <<< "$out" && grep -Fq "without $required" <<< "$out" || {
        printf 'global %s block was not diagnosed:\n%s\n' "$case_name" "$out" >&2
        exit 1
    }
done
echo 'block global authority smoke OK'
