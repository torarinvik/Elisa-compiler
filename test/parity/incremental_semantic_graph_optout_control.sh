#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-semantic-graph-optout.XXXXXX")"
SERVER_PID=""
cleanup() {
    if [[ -n "$SERVER_PID" ]]; then
        kill -TERM -- "-$SERVER_PID" 2>/dev/null || true
        local cleanup_attempt=0
        while (( cleanup_attempt < 20 )) && kill -0 -- "-$SERVER_PID" 2>/dev/null; do
            sleep 0.1
            cleanup_attempt=$((cleanup_attempt + 1))
        done
        kill -KILL -- "-$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    exec 3>&- 2>/dev/null || true
    exec 4<&- 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT INT TERM HUP

SOURCE="$WORK/session.elisa"
REQUESTS="$WORK/requests"
REPLIES="$WORK/replies"
SERVER_LOG="$WORK/server.stderr"
REPORTS="$WORK/reports"
write_source() {
    cat >"$SOURCE" <<EOF
def helper() -> i64:
    return $1

def bad() -> i64:
    return graph_optout_missing_name

def main() -> i64:
    return helper()
EOF
}
fail() {
    echo "incremental semantic graph opt-out control FAILED: $1" >&2
    [[ ! -f "$SERVER_LOG" ]] || cat "$SERVER_LOG" >&2
    exit 1
}
send_check() {
    local expected_status="$1"
    local previous_reports previous_diagnostics diagnostic_count actual
    previous_reports="$(grep -Ec '^incremental-ga-cache:' "$SERVER_LOG" || true)"
    previous_diagnostics="$(grep -Fc 'graph_optout_missing_name' "$SERVER_LOG" || true)"
    printf 'check\n' >&3 || fail "could not send check request"
    if ! IFS= read -r -t 120 -u 4 actual; then
        fail "timed out waiting for semantic-session status $expected_status"
    fi
    [[ "$actual" == "$expected_status" ]] || fail "expected status $expected_status, got $actual"
    local report_count
    report_count="$(grep -Ec '^incremental-ga-cache:' "$SERVER_LOG" || true)"
    [[ "$report_count" -eq "$((previous_reports + 1))" ]] || fail "expected one cache report, got $previous_reports->$report_count"
    diagnostic_count="$(grep -Fc 'graph_optout_missing_name' "$SERVER_LOG" || true)"
    [[ "$diagnostic_count" -eq "$((previous_diagnostics + 1))" ]] \
        || fail "expected exactly one unresolved-name diagnostic, got $previous_diagnostics->$diagnostic_count"
    grep -E '^incremental-ga-cache:.* session=(hit|edit|miss|off)([[:space:]]|$)' "$SERVER_LOG" | tail -n 1 >>"$REPORTS"
}
assert_report() {
    local report="$1"
    local pattern="$2"
    local description="$3"
    [[ "$report" =~ $pattern ]] || fail "$description: $report"
}

mkfifo "$REQUESTS" "$REPLIES"
: >"$SERVER_LOG"
: >"$REPORTS"
write_source 40
env -u ELISA_STAGE1_PERMISSIVE -u ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH \
    ELISA_STAGE1_BIN="$STAGE1" ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 \
    "${PYTHON_BIN:-python3}" -c 'import os, sys; os.setsid(); os.execvp("bash", ["bash", *sys.argv[1:]])' \
    "$ROOT/scripts/elisac_stage1.sh" semantic-session "$SOURCE" \
    <"$REQUESTS" >"$REPLIES" 2>"$SERVER_LOG" &
SERVER_PID=$!
exec 3>"$REQUESTS"
exec 4<"$REPLIES"

send_check 1
send_check 1
write_source 41
send_check 1
edited_report="$(tail -n 1 "$REPORTS")"
assert_report "$edited_report" 'session=edit([[:space:]]|$)' "body edit did not reuse the retained snapshot"
assert_report "$edited_report" 'source_input_admitted=no([[:space:]]|$)' "default session unexpectedly admitted a query-graph source node"
assert_report "$edited_report" 'function_body_facts_restored=0([[:space:]]|$)' "default session unexpectedly restored graph facts"
assert_report "$edited_report" 'prior_snapshot_fact_fallbacks=1([[:space:]]|$)' "default session did not use the typed-snapshot fallback"
assert_report "$edited_report" 'cold_body_scans=2([[:space:]]|$)' "expected the edited helper and unsupported diagnostic body to be cold-scanned"

cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/cold.stdout" 2>"$WORK/cold.stderr" || cold_status=$?
[[ "$cold_status" -eq 1 ]] || fail "cold check expected a semantic error, got status $cold_status"
cold_diagnostic="$(grep -F 'graph_optout_missing_name' "$WORK/cold.stderr" | tail -n 1 || true)"
[[ "$(grep -Fc 'graph_optout_missing_name' "$WORK/cold.stderr" || true)" -eq 1 ]] \
    || fail "cold check did not emit exactly one unresolved-name diagnostic"
warm_edit_diagnostic="$(grep -F 'graph_optout_missing_name' "$SERVER_LOG" | tail -n 1 || true)"
[[ -n "$cold_diagnostic" && "$warm_edit_diagnostic" == "$cold_diagnostic" ]] \
    || fail "default-off edit diagnostic differs from cold: cold=[$cold_diagnostic] warm=[$warm_edit_diagnostic]"

send_check 1
hit_report="$(tail -n 1 "$REPORTS")"
assert_report "$hit_report" 'session=hit([[:space:]]|$)' "repeated invalid source did not hit its retained snapshot"
warm_hit_diagnostic="$(grep -F 'graph_optout_missing_name' "$SERVER_LOG" | tail -n 1 || true)"
[[ "$warm_hit_diagnostic" == "$cold_diagnostic" ]] \
    || fail "default-off exact-hit diagnostic differs from cold: cold=[$cold_diagnostic] warm=[$warm_hit_diagnostic]"

printf 'quit\n' >&3 || fail "could not send quit command"
exec 3>&-
if ! wait "$SERVER_PID"; then
    SERVER_PID=""
    fail "semantic-session host exited unsuccessfully"
fi
SERVER_PID=""
exec 4<&-
echo "incremental semantic graph opt-out control passed: default-off graph, typed-snapshot fallback, and cold diagnostic parity"
