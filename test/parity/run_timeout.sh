# shellcheck shell=bash
# One load-tolerant way to run a compiled program under a time budget.
#
# Phase T, 2026-09-06: once the gate runs many checks at once (and two gates can share a
# host), a program that finishes in two seconds idle can miss a 10-20 s budget, and the
# harness then compares `got 124` against `want 42` and reports a WRONG ANSWER. Measured in
# one loaded run: 8 fabricated corpus mismatches plus 16 in backend_obj — none reproducible
# standalone. A timeout is the ABSENCE of an answer, so it must not be scored as a different
# one: expire once, retry with a much larger budget, and only then believe it. A genuine
# runaway expires both budgets and still fails, at the cost of one extra wait per real hang.
#
#   source "$REPO_ROOT/test/parity/run_timeout.sh"
#   RUN() { elisa_run_timeout 15 "$@"; }
#
# ELISA_TIMEOUT_ESCALATE (default 6) scales the retry; the retry is capped at 900 s. Output
# is buffered and printed once, from whichever attempt produced the verdict — streaming both
# attempts would concatenate a truncated run with a complete one.
elisa_run_timeout() {
    local budget="$1"; shift
    if ! command -v timeout >/dev/null 2>&1; then "$@"; return $?; fi
    local out err status retry
    out="$(mktemp)"; err="$(mktemp)"
    timeout "$budget" "$@" >"$out" 2>"$err"; status=$?
    if [ "$status" -eq 124 ]; then
        retry=$(( budget * ${ELISA_TIMEOUT_ESCALATE:-6} ))
        [ "$retry" -gt 900 ] && retry=900
        timeout "$retry" "$@" >"$out" 2>"$err"; status=$?
    fi
    cat "$out"; cat "$err" >&2
    rm -f "$out" "$err"
    return "$status"
}
