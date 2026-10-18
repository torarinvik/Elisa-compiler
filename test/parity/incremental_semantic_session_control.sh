#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-semantic-session.XXXXXX")"
SERVER_PID=""
cleanup() {
    if [[ -n "$SERVER_PID" ]]; then
        # The host wrapper starts the guarded compiler as a child. Keep the wrapper
        # and product in their own process group so failure cleanup stops both.
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
REPORTS="$WORK/session-reports"
mkfifo "$REQUESTS" "$REPLIES"
: >"$REPORTS"

write_valid_source() {
    local result="$1"
    local shifted="${2:-0}"
    cat >"$SOURCE" <<EOF
def helper() -> i64:
    return 40
EOF
    if [[ "$shifted" == 1 ]]; then
        printf '# source-position shift\n' >>"$SOURCE"
    fi
    cat >>"$SOURCE" <<EOF

def lint() -> i64:
    value: mutable i64 = 40
    value <- value
    return value

def captured_lint() -> i64:
    state: mutable i64 = 0
    while state > 0 |state|:
        state <- state
        state <- state - 1
    return state

def main() -> i64:
    return helper() + $result
EOF
}

fail() {
    echo "incremental semantic-session control FAILED: $1" >&2
    if [[ -f "$WORK/server.stderr" ]]; then
        cat "$WORK/server.stderr" >&2
    fi
    exit 1
}

# Exercise the exact retained-field shape used by the session: a generic struct
# whose byte buffer is allocated in its declared region. The paired negative
# control ensures a request-borrowed view cannot be stored into a longer-lived
# session region.
region_layout_output="$WORK/session-region-layout.ll"
if ! "$STAGE1" -emit llvm -O0 -o "$region_layout_output" "$ROOT/test/repro/incremental_session_region_storage.elisa" >"$WORK/session-region-layout.log" 2>&1; then
    fail "Stage1 rejected a region-owned byte buffer in a generic retained struct: $(tail -n 8 "$WORK/session-region-layout.log")"
fi
borrowed_source_output="$WORK/session-borrowed-source.ll"
if "$STAGE1" -emit llvm -O0 -o "$borrowed_source_output" "$ROOT/test/repro/incremental_session_borrowed_source.neg.elisa" >"$WORK/session-borrowed-source.log" 2>&1; then
    fail "Stage1 accepted a request-borrowed view stored in the longer-lived session region"
fi
grep -Eq 'short-lived region escapes via store into longer-lived storage|stored into longer-lived region' "$WORK/session-borrowed-source.log" \
    || fail "Stage1 rejected the borrowed-source control for an unrelated reason: $(tail -n 8 "$WORK/session-borrowed-source.log")"
[[ ! -e "$borrowed_source_output" ]] || fail "Stage1 emitted LLVM for a rejected borrowed-source control"

read_status() {
    local expected="$1"
    local actual=""
    if ! IFS= read -r -t 120 -u 4 actual; then
        fail "timed out waiting for status $expected"
    fi
    [[ "$actual" == "$expected" ]] || fail "expected status $expected, got $actual"
}

send_check() {
    local expected="$1"
    local reports_before
    reports_before="$(grep -Ec 'session=(hit|edit|miss|off)([[:space:]]|$)' "$WORK/server.stderr" || true)"
    printf 'check\n' >&3 || fail "could not send check command"
    read_status "$expected"
    local report_line
    report_line="$(grep -E 'session=(hit|edit|miss|off)([[:space:]]|$)' "$WORK/server.stderr" | tail -n 1 || true)"
    local reports_after
    reports_after="$(grep -Ec 'session=(hit|edit|miss|off)([[:space:]]|$)' "$WORK/server.stderr" || true)"
    [[ "$reports_after" -eq "$((reports_before + 1))" ]] || fail "expected one cache report for this request, got $reports_before->$reports_after"
    [[ -n "$report_line" ]] || fail "missing cache report for this request"
    printf '%s\n' "$report_line" >>"$REPORTS"
}

assert_no_graph_restore() {
    local report="$1"
    local context="$2"
    [[ ! "$report" =~ session=hit([[:space:]]|$) ]] \
        || fail "$context unexpectedly hit the retained session: $report"
    [[ "$report" =~ source_input_admitted=no([[:space:]]|$) ]] \
        || fail "$context unexpectedly admitted the previous declaration surface: $report"
    [[ "$report" =~ function_body_facts_restored=0([[:space:]]|$) ]] \
        || fail "$context restored function facts across a changed input surface: $report"
}

write_valid_source 1
ELISA_STAGE1_BIN="$STAGE1" ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 \
    "${PYTHON_BIN:-python3}" -c 'import os, sys; os.setsid(); os.execvp("bash", ["bash", *sys.argv[1:]])' \
    "$ROOT/scripts/elisac_stage1.sh" semantic-session "$SOURCE" \
    <"$REQUESTS" >"$REPLIES" 2>"$WORK/server.stderr" &
SERVER_PID=$!
exec 3>"$REQUESTS"
exec 4<"$REPLIES"

# First request seeds a small session snapshot.
send_check 0
send_check 0

# A body edit and inserted comment shift unchanged lint bodies by one line. Their
# reused anchors must point to the new source positions.
write_valid_source 2 1
send_check 0

# Grow request and retained snapshot vectors, plus the include identity key. Then
# repeat the large check after the previous request region has ended; it must read
# only the session-owned copies of source, identity, and function facts.
write_growth_source() {
    : >"$SOURCE"
    local index
    for ((index = 0; index < 128; index++)); do
        cat >"$WORK/growth_${index}.elisa" <<EOF
def growth_${index}() -> i64:
    return ${index}
EOF
        printf 'include "growth_%s.elisa"\n' "$index" >>"$SOURCE"
    done
    cat >>"$SOURCE" <<'EOF'
def main() -> i64:
    return growth_127()
EOF
}
write_growth_source
send_check 0
send_check 0
large_repeat_report="$(sed -n '5p' "$REPORTS")"
[[ "$large_repeat_report" =~ session=hit([[:space:]]|$) ]] || fail "expected the repeated large-source request to hit its retained snapshot: $large_repeat_report"
if [[ "$large_repeat_report" =~ eligible_bodies=([0-9]+) ]]; then
    large_eligible_bodies="${BASH_REMATCH[1]}"
else
    fail "expected eligible-body accounting on the repeated large-source request: $large_repeat_report"
fi
if [[ "$large_repeat_report" =~ matched_eligible_bodies=([0-9]+) ]]; then
    large_matched_eligible_bodies="${BASH_REMATCH[1]}"
else
    fail "expected matched-body accounting on the repeated large-source request: $large_repeat_report"
fi
[[ "$large_eligible_bodies" -ge 100 && "$large_matched_eligible_bodies" -eq "$large_eligible_bodies" ]] \
    || fail "expected every large-source body to match its retained fact: $large_repeat_report"

# A changed body that introduces an unresolved name must be diagnosed. Repeating the
# same invalid source must remain rejected instead of returning a stale accepted result.
cat >"$SOURCE" <<'EOF'
def helper() -> i64:
    return 40
# source-position shift

def lint() -> i64:
    value: mutable i64 = 40
    value <- value
    return value

def captured_lint() -> i64:
    state: mutable i64 = 0
    while state > 0 |state|:
        state <- state
        state <- state - 1
    return state

def main() -> i64:
    return unknown_name
EOF
invalid_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/invalid-cold.stdout" 2>"$WORK/invalid-cold.stderr" || invalid_cold_status=$?
[[ "$invalid_cold_status" -ne 0 ]] || fail "cold check unexpectedly accepted the unresolved-name source"
cold_unknown_diagnostic="$(grep -F 'error:' "$WORK/invalid-cold.stderr" | grep -F 'unknown_name' || true)"
[[ -n "$cold_unknown_diagnostic" ]] || fail "cold check did not report the unresolved name: $(tail -n 8 "$WORK/invalid-cold.stderr")"
cold_unknown_count="$(grep -F 'error:' "$WORK/invalid-cold.stderr" | grep -Fc 'unknown_name' || true)"
[[ "$cold_unknown_count" -eq 1 ]] || fail "expected one cold unresolved-name diagnostic, got $cold_unknown_count"
send_check 1
first_warm_unknown_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'unknown_name' | tail -n 1 || true)"
first_warm_unknown_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'unknown_name' || true)"
[[ "$first_warm_unknown_count" -eq 1 && "$first_warm_unknown_diagnostic" == "$cold_unknown_diagnostic" ]] \
    || fail "first warm diagnostic differs from cold or has wrong multiplicity: cold=[$cold_unknown_diagnostic] warm_count=$first_warm_unknown_count warm=[$first_warm_unknown_diagnostic]"
send_check 1
second_warm_unknown_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'unknown_name' | tail -n 1 || true)"
second_warm_unknown_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'unknown_name' || true)"
[[ "$second_warm_unknown_count" -eq 2 && "$second_warm_unknown_diagnostic" == "$cold_unknown_diagnostic" ]] \
    || fail "repeated warm diagnostic differs from cold or has wrong multiplicity: cold=[$cold_unknown_diagnostic] warm_count=$second_warm_unknown_count warm=[$second_warm_unknown_diagnostic]"

write_valid_source 2 1
send_check 0

# A warm root source that imports another file must not keep its previous result
# when only the included file's body changes. Compare the retained host's error
# and recovery with cold checks so include identity participates in invalidation.
INCLUDED="$WORK/included-helper.elisa"
cat >"$INCLUDED" <<'EOF'
def include_helper() -> i64:
    return 40
EOF
cat >"$SOURCE" <<'EOF'
include "included-helper.elisa"

def main() -> i64:
    return include_helper()
EOF
send_check 0
include_seed_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$include_seed_report" "the new include surface"

cat >"$INCLUDED" <<'EOF'
def include_helper() -> i64:
    return include_stale_symbol
EOF
include_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/include-cold.stdout" 2>"$WORK/include-cold.stderr" || include_cold_status=$?
[[ "$include_cold_status" -ne 0 ]] || fail "cold check accepted the unresolved name from an edited include"
include_cold_diagnostic="$(grep -F 'error:' "$WORK/include-cold.stderr" | grep -F 'include_stale_symbol' | tail -n 1 || true)"
[[ -n "$include_cold_diagnostic" ]] || fail "cold check missed the unresolved name from the edited include"
send_check 1
include_edit_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$include_edit_report" "the edited include"
include_warm_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'include_stale_symbol' | tail -n 1 || true)"
[[ "$include_warm_diagnostic" == "$include_cold_diagnostic" ]] \
    || fail "edited-include diagnostic differs from cold: cold=[$include_cold_diagnostic] warm=[$include_warm_diagnostic]"
send_check 1
include_repeat_report="$(tail -n 1 "$REPORTS")"
[[ "$include_repeat_report" =~ session=hit([[:space:]]|$) ]] \
    || fail "expected an exact hit for the repeated invalid include: $include_repeat_report"
include_repeat_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'include_stale_symbol' | tail -n 1 || true)"
[[ "$include_repeat_diagnostic" == "$include_cold_diagnostic" ]] \
    || fail "repeated invalid-include diagnostic differs from cold: cold=[$include_cold_diagnostic] warm=[$include_repeat_diagnostic]"

cat >"$INCLUDED" <<'EOF'
def include_helper() -> i64:
    return 41
EOF
send_check 0
include_recovery_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$include_recovery_report" "the recovered include"

# Changing a function parameter type changes the declaration surface even when
# that function's body bytes are identical. The session must invalidate body
# facts whose result could depend on the changed signature.
cat >"$SOURCE" <<'EOF'
def signature_helper(value: i64) -> i64:
    return 40

def main() -> i64:
    return signature_helper(1)
EOF
send_check 0
cat >"$SOURCE" <<'EOF'
def signature_helper(value: bool) -> i64:
    return 40

def main() -> i64:
    return signature_helper(true)
EOF
signature_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/signature-cold.stdout" 2>"$WORK/signature-cold.stderr" || signature_cold_status=$?
[[ "$signature_cold_status" -eq 0 ]] || fail "cold check rejected the signature-edited source: $(tail -n 8 "$WORK/signature-cold.stderr")"
send_check 0
signature_edit_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$signature_edit_report" "the signature edit"

printf 'quit\n' >&3 || fail "could not send quit command"
exec 3>&-
if ! wait "$SERVER_PID"; then
    SERVER_PID=""
    fail "semantic-session host exited unsuccessfully"
fi
SERVER_PID=""
exec 4<&-

[[ -s "$WORK/server.stderr" ]] || fail "expected diagnostics and cache reports on stderr"
grep -Fq 'unknown_name' "$WORK/server.stderr" || fail "missing diagnostic for edited unresolved name"
lint_warning_count="$(grep -Fc 'assignment to "value" has no effect: target and value are identical' "$WORK/server.stderr" || true)"
[[ "$lint_warning_count" -eq 6 ]] || fail "expected the current self-assignment warning on all six requests containing that function, got $lint_warning_count"
captured_lint_warning_count="$(grep -Fc 'assignment to "state" has no effect: target and value are identical' "$WORK/server.stderr" || true)"
[[ "$captured_lint_warning_count" -eq 6 ]] || fail "expected the captured-loop warning on all six requests containing that function, got $captured_lint_warning_count"
count_warning_at() {
    local name="$1"
    local line="$2"
    awk -v line="$line" -v name="$name" '
        $0 ~ ("/session[.]elisa:" line ":[0-9]+: warning: assignment to \"" name "\" has no effect: target and value are identical") {
            count++
        }
        END { print count + 0 }
    ' "$WORK/server.stderr"
}
value_line6_count="$(count_warning_at value 6)"
value_line7_count="$(count_warning_at value 7)"
state_line12_count="$(count_warning_at state 12)"
state_line13_count="$(count_warning_at state 13)"
[[ "$value_line6_count" -eq 2 && "$value_line7_count" -eq 4 ]] || fail "expected straight-line warning anchors to shift from line 6 to 7, got $value_line6_count/$value_line7_count"
[[ "$state_line12_count" -eq 2 && "$state_line13_count" -eq 4 ]] || fail "expected captured-loop warning anchors to shift from line 12 to 13, got $state_line12_count/$state_line13_count"
shifted_report="$(sed -n '3p' "$REPORTS")"
[[ "$shifted_report" =~ session=edit([[:space:]]|$) ]] || fail "expected the inserted-line request to reuse the prior semantic snapshot: $shifted_report"
[[ "$shifted_report" =~ self_assignment_bodies_reused=2([[:space:]]|$) ]] || fail "expected exactly two complete self-assignment body ranges to reuse on the inserted-line request: $shifted_report"
[[ "$shifted_report" =~ function_body_facts_restored=[1-9][0-9]*([[:space:]]|$) ]] || fail "expected a query-graph body-fact restore on the inserted-line request: $shifted_report"
[[ "$shifted_report" =~ source_input_admitted=yes([[:space:]]|$) ]] || fail "expected the unchanged declaration surface to be admitted by the query graph: $shifted_report"
cold_report="$(sed -n '1p' "$REPORTS")"
if [[ "$cold_report" =~ visited=([0-9]+) ]]; then
    cold_visited="${BASH_REMATCH[1]}"
else
    fail "expected body-walk accounting on the cold request: $cold_report"
fi
if [[ "$shifted_report" =~ visited=([0-9]+) ]]; then
    shifted_visited="${BASH_REMATCH[1]}"
else
    fail "expected body-walk accounting on the edited request: $shifted_report"
fi
[[ "$shifted_visited" -lt "$cold_visited" ]] \
    || fail "expected graph hits to skip at least one unchanged eligible body walk: cold=$cold_visited edited=$shifted_visited"
hit_count="$(grep -Ec 'session=hit([[:space:]]|$)' "$WORK/server.stderr" || true)"
edit_count="$(grep -Ec 'session=edit([[:space:]]|$)' "$WORK/server.stderr" || true)"
lint_reuse_count="$(grep -Ec 'self_assignment_bodies_reused=[1-9][0-9]*' "$WORK/server.stderr" || true)"
[[ "$hit_count" -ge 2 ]] || fail "expected at least two exact session hits, got $hit_count"
[[ "$edit_count" -ge 2 ]] || fail "expected body-fact reuse after edits, got $edit_count"
[[ "$lint_reuse_count" -ge 4 ]] || fail "expected self-assignment replay on repeated and edited requests, got $lint_reuse_count"

echo "incremental semantic-session control OK: region storage, borrowed-source rejection, growth after teardown, exact hits, edit reuse, location rebinding, loop fallback, and error invalidation"
