#!/usr/bin/env bash
# A retained compile-session must emit the same module-local names on every request as a
# fresh one-shot compiler process. Lambdas exercise the backend's lifted-symbol counter.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-compile-session-state.XXXXXX")"
ACTIVE_PID=""
cleanup() {
    if [[ -n "$ACTIVE_PID" ]]; then
        kill -TERM -- "-$ACTIVE_PID" 2>/dev/null || true
        local cleanup_attempt=0
        while (( cleanup_attempt < 20 )) && kill -0 -- "-$ACTIVE_PID" 2>/dev/null; do
            sleep 0.1
            cleanup_attempt=$((cleanup_attempt + 1))
        done
        kill -KILL -- "-$ACTIVE_PID" 2>/dev/null || true
        wait "$ACTIVE_PID" 2>/dev/null || true
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

run_isolated() {
    python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" &
    ACTIVE_PID=$!
    local run_status=0
    wait "$ACTIVE_PID" || run_status=$?
    ACTIVE_PID=""
    return "$run_status"
}

SOURCE="$ROOT/test/repro/lambda_in_local.elisa"
ONE_SHOT="$WORK/one-shot.ll"
SESSION="$WORK/session.ll"
REQUESTS="$WORK/requests"
STATUS="$WORK/status"
LOG="$WORK/session.log"

if ! run_isolated "$STAGE1" -emit llvm -O0 -o "$ONE_SHOT" "$SOURCE" >"$WORK/one-shot.log" 2>&1; then
    echo "compile-session module-state smoke FAILED: one-shot compile failed" >&2
    cat "$WORK/one-shot.log" >&2
    exit 1
fi

printf 'compile\ncompile\nquit\n' >"$REQUESTS"
if ! ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 run_isolated "$STAGE1" compile-session -emit llvm -O0 -o "$SESSION" "$SOURCE" \
    <"$REQUESTS" >"$STATUS" 2>"$LOG"; then
    echo "compile-session module-state smoke FAILED: retained host exited unsuccessfully" >&2
    cat "$LOG" >&2
    exit 1
fi

if [[ "$(cat "$STATUS")" != $'0\n0' ]]; then
    echo "compile-session module-state smoke FAILED: expected two accepted requests, got:" >&2
    cat "$STATUS" >&2
    cat "$LOG" >&2
    exit 1
fi

report_count="$(grep -Ec 'session=(hit|edit|miss|off)([[:space:]]|$)' "$LOG" || true)"
if [[ "$report_count" -ne 2 ]]; then
    echo "compile-session module-state smoke FAILED: expected two semantic-session reports, got $report_count" >&2
    cat "$LOG" >&2
    exit 1
fi
last_report="$(grep -E 'session=(hit|edit|miss|off)([[:space:]]|$)' "$LOG" | tail -n 1)"
if [[ ! "$last_report" =~ session=hit([[:space:]]|$) ]]; then
    echo "compile-session module-state smoke FAILED: the unchanged second request did not hit the retained semantic session" >&2
    cat "$LOG" >&2
    exit 1
fi

if ! cmp -s "$ONE_SHOT" "$SESSION"; then
    echo "compile-session module-state smoke FAILED: repeated module emission differs from one-shot output" >&2
    diff -u "$ONE_SHOT" "$SESSION" | head -n 80 >&2 || true
    exit 1
fi

echo "compile-session module-state smoke passed"
