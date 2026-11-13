#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
out="$("$RPT" < "$REPO_ROOT/test/repro/region_overload_receiver_conflict.elisa")"
grep -q '^P 0$' <<< "$out"
if ! grep -Fq 'duplicate declaration "route"' <<< "$out"; then
    printf 'same-receiver region overloads must be diagnosed:\n%s\n' "$out" >&2
    exit 1
fi
source_text="$(cat "$REPO_ROOT/test/repro/region_overload_receiver_conflict.elisa")"
receiver_before='ticket: i64, pair: Pair[r, s]'
receiver_after='ticket: bool, pair: Pair[r, s]'
distinct_receiver="${source_text/"$receiver_before"/$receiver_after}"
out="$("$RPT" <<< "$distinct_receiver")"
grep -q '^P 0$' <<< "$out"
if grep -Fq 'duplicate declaration "route"' <<< "$out"; then
    printf 'distinct receiver overloads were rejected:\n%s\n' "$out" >&2
    exit 1
fi
type_before='pair: Pair[r, s]'
type_after='pair: Pair[r, i64]'
nonregion_type="${source_text/"$type_before"/$type_after}"
out="$("$RPT" <<< "$nonregion_type")"
grep -q '^P 0$' <<< "$out"
if grep -Fq 'duplicate declaration "route"' <<< "$out"; then
    printf 'non-region argument was mistaken for a region:\n%s\n' "$out" >&2
    exit 1
fi
echo 'region overload receiver conflict OK'
