#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "partial backend output smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-partial-backend.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

DECLINED="$ROOT/test/parity/fixtures/partial_body_decline.elisa"
for mode in llvm obj bc exe; do
    output="$WORK/declined-$mode"
    log="$output.log"
    if "$STAGE1" -emit "$mode" -o "$output" "$DECLINED" >"$log" 2>&1; then
        echo "partial backend output smoke: stage1 accepted an incomplete $mode artifact" >&2
        cat "$log" >&2
        exit 1
    fi
    rg -Fq 'error: backend declined 1 function body(ies); the object does not define: create' "$log" || {
        echo "partial backend output smoke: missing declined-body diagnostic for $mode" >&2
        cat "$log" >&2
        exit 1
    }
    rg -Fq 'no artifact was written' "$log" || { echo "partial backend output smoke: missing no-artifact guarantee for $mode" >&2; cat "$log" >&2; exit 1; }
    [[ ! -e "$output" && ! -e "$output.o" ]] || { echo "partial backend output smoke: wrote output despite declining a body for $mode" >&2; exit 1; }
done

CONTROL="$ROOT/test/parity/fixtures/backend_decline_control.elisa"
for optimization in 0 2; do
    executable="$WORK/control-O$optimization"
    "$STAGE1" -emit exe "-O$optimization" -o "$executable" "$CONTROL" >"$executable.compile.log" 2>&1 || {
        echo "partial backend output smoke: valid control failed at O$optimization" >&2
        cat "$executable.compile.log" >&2
        exit 1
    }
    log="$executable.run.log"
    set +e
    elisa_run_timeout 10 "$executable" >"$log" 2>&1
    run_status=$?
    set -e
    [[ "$run_status" -eq 0 ]] || { echo "partial backend output smoke: valid control failed at runtime (status $run_status)" >&2; cat "$log" >&2; exit 1; }
done

echo "partial backend output smoke OK: partial LLVM/object/bitcode/executable emission is rejected before writing; valid controls pass at O0/O2"
