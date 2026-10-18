#!/usr/bin/env bash
set -euo pipefail
# Keep bytewise parity checks independent of profiling and trace settings inherited from the caller.
unset ELISA_STAGE1_TIMINGS ELISA_STAGE1_TRACE

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/test/parity/test_incremental_compile_session_control.py"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-compile-session.XXXXXX")"
SOURCE="$WORK/session.elisa"
REQUESTS="$WORK/requests"
REPLIES="$WORK/replies"
SERVER_LOG="$WORK/server.stderr"
SERVER_PID=""
LAST_REPORT=""
LAST_REQUEST_STDERR=""

cleanup() {
    if [[ -n "$SERVER_PID" ]]; then
        # compile-session may have solver or tool children. Keep the process tree in its
        # own group so a failed assertion cannot leave them blocked on the request FIFO.
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
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

fail() {
    echo "incremental compile-session control FAILED: $1" >&2
    if [[ -f "$SERVER_LOG" ]]; then
        cat "$SERVER_LOG" >&2
    fi
    exit 1
}

write_source() {
    local value="$1"
    cat >"$SOURCE" <<EOF
def helper() -> i64:
    return $value

def main() -> i64:
    return helper()
EOF
}

cold_object() {
    local stem="$1"
    if ! env -u ELISA_STAGE1_PERMISSIVE -u ELISA_STAGE1_INCREMENTAL_CACHE_DIR -u ELISA_STAGE1_INCREMENTAL_CACHE_REPORT \
        "$STAGE1" -emit obj -O0 -o "$WORK/$stem.o" "$SOURCE" >"$WORK/$stem.stdout" 2>"$WORK/$stem.stderr"; then
        fail "cold $stem object compile failed: $(tail -n 8 "$WORK/$stem.stderr")"
    fi
}

read_status() {
    local expected="$1"
    local actual=""
    if ! IFS= read -r -t 120 -u 4 actual; then
        fail "timed out waiting for status $expected"
    fi
    [[ "$actual" == "$expected" ]] || fail "expected status $expected, got $actual"
}

send_compile() {
    local expected_status="$1"
    local expected_session="$2"
    local reports_before reports_after report_line lines_before lines_after
    reports_before="$(grep -Ec '^incremental-ga-cache:' "$SERVER_LOG" || true)"
    lines_before="$(wc -l < "$SERVER_LOG")"
    printf 'compile\n' >&3 || fail "could not send compile request"
    read_status "$expected_status"
    report_line="$(grep -E '^incremental-ga-cache:.* session=(hit|edit|miss|off)([[:space:]]|$)' "$SERVER_LOG" | tail -n 1 || true)"
    reports_after="$(grep -Ec '^incremental-ga-cache:' "$SERVER_LOG" || true)"
    [[ "$reports_after" -eq "$((reports_before + 1))" ]] || fail "expected one cache report, got $reports_before->$reports_after"
    [[ "$report_line" =~ session=$expected_session([[:space:]]|$) ]] \
        || fail "expected session=$expected_session, got: $report_line"
    LAST_REPORT="$report_line"
    # The cache report precedes backend work. The status, rather than that
    # report, completes the request and therefore delimits its diagnostic stream.
    lines_after="$(wc -l < "$SERVER_LOG")"
    LAST_REQUEST_STDERR="$WORK/request-$reports_after.stderr"
    : >"$LAST_REQUEST_STDERR"
    if (( lines_after > lines_before )); then
        sed -n "$((lines_before + 1)),${lines_after}p" "$SERVER_LOG" \
            | sed '/^incremental-ga-cache:/d' >"$LAST_REQUEST_STDERR"
    fi
}

compare_object() {
    local cold="$1"
    if ! cmp -s "$WORK/$cold.o" "$WORK/session.o"; then
        echo "incremental compile-session control FAILED: $cold object differs from the retained compile" >&2
        cmp -l "$WORK/$cold.o" "$WORK/session.o" | head -n 20 >&2 || true
        exit 1
    fi
}

assert_graph_body_edit() {
    local report="$LAST_REPORT"
    local restored cold_scans
    [[ "$report" =~ source_input_admitted=yes([[:space:]]|$) ]] \
        || fail "body edit did not admit the unchanged SourceInput query: $report"
    if [[ "$report" =~ function_body_facts_restored=([0-9]+) ]]; then
        restored="${BASH_REMATCH[1]}"
    else
        fail "body edit report omitted graph-restored body count: $report"
    fi
    if [[ "$report" =~ cold_body_scans=([0-9]+) ]]; then
        cold_scans="${BASH_REMATCH[1]}"
    else
        fail "body edit report omitted cold body-scan count: $report"
    fi
    [[ "$restored" -eq 1 ]] || fail "expected exactly the unchanged main body to restore from the query graph: $report"
    [[ "$cold_scans" -eq 1 ]] || fail "expected only the edited helper body to be cold-scanned: $report"
}

write_source 40
cold_object cold-first
mkfifo "$REQUESTS" "$REPLIES"
env -u ELISA_STAGE1_PERMISSIVE -u ELISA_STAGE1_INCREMENTAL_CACHE_DIR ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH=1 ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 \
    "${PYTHON_BIN:-python3}" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' \
    "$STAGE1" compile-session -emit obj -O0 -o "$WORK/session.o" "$SOURCE" \
    <"$REQUESTS" >"$REPLIES" 2>"$SERVER_LOG" &
SERVER_PID=$!
exec 3>"$REQUESTS"
exec 4<"$REPLIES"

send_compile 0 miss
compare_object cold-first
send_compile 0 hit
compare_object cold-first

# Editing only the helper must preserve object parity and reuse the unchanged main.
write_source 41
cold_object cold-edited
send_compile 0 edit
assert_graph_body_edit
compare_object cold-edited

# Errorful translation units must remain rejected, replay the same diagnostic on
# an exact repeat, and recover after a subsequent valid edit.
cat >"$SOURCE" <<'EOF'
def helper() -> i64:
    return unknown_helper

def main() -> i64:
    return unknown_name
EOF
invalid_status=0
env -u ELISA_STAGE1_PERMISSIVE -u ELISA_STAGE1_INCREMENTAL_CACHE_DIR -u ELISA_STAGE1_INCREMENTAL_CACHE_REPORT \
    "$STAGE1" -emit obj -O0 -o "$WORK/invalid-cold.o" "$SOURCE" >"$WORK/invalid-cold.stdout" 2>"$WORK/invalid-cold.stderr" || invalid_status=$?
[[ "$invalid_status" -ne 0 ]] || fail "cold compile unexpectedly accepted the unresolved-name source"
cp "$WORK/invalid-cold.stderr" "$WORK/invalid-cold.diagnostics"
[[ -s "$WORK/invalid-cold.diagnostics" ]] || fail "cold compile did not emit diagnostics"
grep -Fq 'unknown_helper' "$WORK/invalid-cold.diagnostics" \
    || fail "cold compile did not report the helper's unresolved name"
grep -Fq 'unknown_name' "$WORK/invalid-cold.diagnostics" \
    || fail "cold compile did not report the entry point's unresolved name"

send_compile 1 edit
if ! cmp -s "$WORK/invalid-cold.diagnostics" "$LAST_REQUEST_STDERR"; then
    echo "incremental compile-session control FAILED: first warm diagnostics differ from cold" >&2
    diff -u "$WORK/invalid-cold.diagnostics" "$LAST_REQUEST_STDERR" >&2 || true
    exit 1
fi

send_compile 1 hit
if ! cmp -s "$WORK/invalid-cold.diagnostics" "$LAST_REQUEST_STDERR"; then
    echo "incremental compile-session control FAILED: repeated warm diagnostics differ from cold" >&2
    diff -u "$WORK/invalid-cold.diagnostics" "$LAST_REQUEST_STDERR" >&2 || true
    exit 1
fi

write_source 42
cold_object cold-recovered
send_compile 0 edit
compare_object cold-recovered

# The root is byte-identical throughout this sequence. An include-only edit
# must invalidate the retained source identity and produce the current object.
INCLUDED_SOURCE="$WORK/included-helper.elisa"
write_included_helper() {
    local value="$1"
    cat >"$INCLUDED_SOURCE" <<EOF
def helper() -> i64:
    return $value
EOF
}
cat >"$SOURCE" <<'EOF'
include "included-helper.elisa"

def main() -> i64:
    return helper()
EOF
cp "$SOURCE" "$WORK/root-before-include-edits.elisa"
write_included_helper 43
cold_object cold-include-first
send_compile 0 edit
compare_object cold-include-first
send_compile 0 hit
compare_object cold-include-first

write_included_helper 44
cmp -s "$SOURCE" "$WORK/root-before-include-edits.elisa" || fail "include edit changed the root fixture"
cold_object cold-include-edited
send_compile 0 edit
compare_object cold-include-edited
send_compile 0 hit
compare_object cold-include-edited

# Returning to an earlier include revision must also yield that revision's bytes.
write_included_helper 43
cmp -s "$SOURCE" "$WORK/root-before-include-edits.elisa" || fail "include restoration changed the root fixture"
send_compile 0 edit
compare_object cold-include-first

printf 'quit\n' >&3 || fail "could not send quit command"
exec 3>&-
if ! wait "$SERVER_PID"; then
    SERVER_PID=""
    fail "compile-session host exited unsuccessfully"
fi
SERVER_PID=""
exec 4<&-

echo "incremental compile-session control passed: object parity, exact hit, body edit, include-only edit/restoration, error diagnostic replay, and recovery"
