#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "named-tuple darray smoke: missing Stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-named-tuple-darray.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for optimization in 0 2; do
    output="$WORK/named-tuple-darray-O$optimization"
    log="$output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/repro/named_tuple_darray_literal.elisa" >"$log" 2>&1 || {
        echo "named-tuple darray smoke: failed to compile nested named-tuple literal at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$output" >"$log" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 123 ]] || {
        echo "named-tuple darray smoke: returned $run_status at O$optimization, expected 123" >&2
        cat "$log" >&2
        exit 1
    }
done

echo "named-tuple darray smoke OK: nested named tuple types register, literals initialize, and indexed fields match at O0/O2"
