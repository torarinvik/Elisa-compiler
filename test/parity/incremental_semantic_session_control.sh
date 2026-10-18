#!/usr/bin/env bash
set -euo pipefail
# Keep bytewise parity checks independent of profiling and trace settings inherited from the caller.
unset ELISA_STAGE1_TIMINGS ELISA_STAGE1_TRACE
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
    return $result
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
    return helper()
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
    local cold_status=0
    local server_bytes_before
    local server_request_stderr="$WORK/server-request.stderr"
    local cold_request_stderr="$WORK/cold-request.stderr"
    "$STAGE1" -emit check "$SOURCE" >"$WORK/cold-request.stdout" 2>"$WORK/cold-request.raw.stderr" || cold_status=$?
    [[ "$cold_status" == "$expected" ]] \
        || fail "cold check status $cold_status differs from expected session status $expected"
    sed '/^incremental-ga-cache:/d' "$WORK/cold-request.raw.stderr" >"$cold_request_stderr"
    server_bytes_before="$(wc -c <"$WORK/server.stderr")"
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
    tail -c "+$((server_bytes_before + 1))" "$WORK/server.stderr" \
        | sed '/^incremental-ga-cache:/d' >"$server_request_stderr"
    if ! diff -u "$cold_request_stderr" "$server_request_stderr"; then
        fail "cold and retained-session diagnostics differ for this request"
    fi
    printf '%s\n' "$report_line" >>"$REPORTS"
}

assert_no_graph_restore() {
    local report="$1"
    local context="$2"
    local expected_cold_scans="${3:-}"
    [[ ! "$report" =~ session=hit([[:space:]]|$) ]] \
        || fail "$context unexpectedly hit the retained session: $report"
    [[ "$report" =~ source_input_admitted=no([[:space:]]|$) ]] \
        || fail "$context unexpectedly admitted the previous declaration surface: $report"
    [[ "$report" =~ function_body_facts_restored=0([[:space:]]|$) ]] \
        || fail "$context restored function facts across a changed input surface: $report"
    [[ "$report" =~ prior_snapshot_fact_fallbacks=0([[:space:]]|$) ]] \
        || fail "$context restored typed snapshot facts across a changed input surface: $report"
    if [[ -n "$expected_cold_scans" ]]; then
        [[ "$report" =~ cold_body_scans=([0-9]+)([[:space:]]|$) ]] \
            || fail "$context report omitted cold body-scan accounting: $report"
        [[ "${BASH_REMATCH[1]}" -eq "$expected_cold_scans" ]] \
            || fail "$context expected $expected_cold_scans cold body scans: $report"
    fi
}

assert_graph_body_edit() {
    local report="$1"
    local context="$2"
    local expected_cold_scans="${3:-1}"
    local cold_body_scans
    local restored_body_facts
    [[ ! "$report" =~ session=hit([[:space:]]|$) ]] \
        || fail "$context unexpectedly hit the retained session: $report"
    [[ "$report" =~ source_input_admitted=yes([[:space:]]|$) ]] \
        || fail "$context failed to admit its unchanged declaration surface: $report"
    if [[ "$report" =~ cold_body_scans=([0-9]+)([[:space:]]|$) ]]; then
        cold_body_scans="${BASH_REMATCH[1]}"
    else
        fail "$context report omitted cold body scan accounting: $report"
    fi
    [[ "$cold_body_scans" -eq "$expected_cold_scans" ]] \
        || fail "$context expected $expected_cold_scans cold body scans: $report"
    if [[ "$report" =~ function_body_facts_restored=([0-9]+)([[:space:]]|$) ]]; then
        restored_body_facts="${BASH_REMATCH[1]}"
    else
        fail "$context report omitted restored body-fact accounting: $report"
    fi
    [[ "$restored_body_facts" -eq 1 ]] \
        || fail "$context did not restore exactly the unchanged function body: $report"
    [[ "$report" =~ prior_snapshot_fact_fallbacks=0([[:space:]]|$) ]] \
        || fail "$context used the prior-snapshot fallback instead of the query graph: $report"
}

assert_body_walker_skips() {
    local report="$1"
    local context="$2"
    local expected="$3"
    local effect_source_skips
    local ungranted_panic_skips
    if [[ "$report" =~ effect_source_bodies_skipped=([0-9]+)([[:space:]]|$) ]]; then
        effect_source_skips="${BASH_REMATCH[1]}"
    else
        fail "$context report omitted effect-source skip accounting: $report"
    fi
    if [[ "$report" =~ ungranted_panic_bodies_skipped=([0-9]+)([[:space:]]|$) ]]; then
        ungranted_panic_skips="${BASH_REMATCH[1]}"
    else
        fail "$context report omitted panic-coverage skip accounting: $report"
    fi
    [[ "$effect_source_skips" -eq "$expected" ]] \
        || fail "$context expected $expected effect-source body skips: $report"
    [[ "$ungranted_panic_skips" -eq "$expected" ]] \
        || fail "$context expected $expected ungranted-panic body skips: $report"
}

write_valid_source 40
ELISA_STAGE1_BIN="$STAGE1" ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH=1 ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 \
    "${PYTHON_BIN:-python3}" -c 'import os, sys; os.setsid(); os.execvp("bash", ["bash", *sys.argv[1:]])' \
    "$ROOT/scripts/elisac_stage1.sh" semantic-session "$SOURCE" \
    <"$REQUESTS" >"$REPLIES" 2>"$WORK/server.stderr" &
SERVER_PID=$!
exec 3>"$REQUESTS"
exec 4<"$REPLIES"

# First request seeds a small session snapshot.
send_check 0
ordinary_seed_report="$(tail -n 1 "$REPORTS")"
assert_body_walker_skips "$ordinary_seed_report" "the ordinary seed" 1
send_check 0
ordinary_repeat_report="$(tail -n 1 "$REPORTS")"
assert_body_walker_skips "$ordinary_repeat_report" "the ordinary repeat" 1

# A supported helper edit and inserted comment leave the declaration surface stable,
# so the unchanged main body can restore while lint warning anchors shift by one line.
write_valid_source 41 1
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
invalid_report="$(tail -n 1 "$REPORTS")"
assert_body_walker_skips "$invalid_report" "the errorful source" 1
first_warm_unknown_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'unknown_name' | tail -n 1 || true)"
first_warm_unknown_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'unknown_name' || true)"
[[ "$first_warm_unknown_count" -eq 1 && "$first_warm_unknown_diagnostic" == "$cold_unknown_diagnostic" ]] \
    || fail "first warm diagnostic differs from cold or has wrong multiplicity: cold=[$cold_unknown_diagnostic] warm_count=$first_warm_unknown_count warm=[$first_warm_unknown_diagnostic]"
send_check 1
second_warm_unknown_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'unknown_name' | tail -n 1 || true)"
second_warm_unknown_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'unknown_name' || true)"
[[ "$second_warm_unknown_count" -eq 2 && "$second_warm_unknown_diagnostic" == "$cold_unknown_diagnostic" ]] \
    || fail "repeated warm diagnostic differs from cold or has wrong multiplicity: cold=[$cold_unknown_diagnostic] warm_count=$second_warm_unknown_count warm=[$second_warm_unknown_diagnostic]"

# An unindexed miss has no symbol/member chain work to skip. Keep it as a
# correctness and add/remove invalidation control without requiring a graph hit.
cat >"$SOURCE" <<'EOF'
def main() -> i64:
    return newly_added_name + 0
EOF
# A body-only edit first recomputes a lookup that the preceding source-surface
# miss could not cache; its next edit must reuse that result without chain work.
name_lookup_hits_from_report() {
    local report="$1"
    if [[ "$report" =~ name_lookup_hits=([0-9]+)([[:space:]]|$) ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        fail "cache report omitted name-lookup hit accounting: $report"
    fi
}
assert_name_lookup_body_edit() {
    local report="$1"
    local context="$2"
    local expected_hits="$3"
    local expected_chain_work="${4:-positive}"
    local chain_visits
    [[ ! "$report" =~ session=hit([[:space:]]|$) ]] \
        || fail "$context unexpectedly hit the complete-file snapshot: $report"
    [[ "$report" =~ source_input_admitted=yes([[:space:]]|$) ]] \
        || fail "$context failed to retain its unchanged declaration surface: $report"
    [[ "$(name_lookup_hits_from_report "$report")" -eq "$expected_hits" ]] \
        || fail "$context expected $expected_hits retained NameLookup hits: $report"
    if [[ "$report" =~ name_lookup_classification_chain_visits=([0-9]+)([[:space:]]|$) ]]; then
        chain_visits="${BASH_REMATCH[1]}"
    else
        fail "$context report omitted classification-chain accounting: $report"
    fi
    if [[ "$expected_hits" -eq 0 ]]; then
        if [[ "$expected_chain_work" == positive ]]; then
            [[ "$chain_visits" -gt 0 ]] \
                || fail "$context recomputed without recording resolver-chain work: $report"
        else
            [[ "$chain_visits" -eq 0 ]] \
                || fail "$context should not need resolver-chain work: $report"
        fi
    else
        [[ "$chain_visits" -eq 0 ]] \
            || fail "$context walked resolver chains despite a retained NameLookup hit: $report"
    fi
}
absent_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/name-absent-cold.stdout" 2>"$WORK/name-absent-cold.stderr" || absent_cold_status=$?
[[ "$absent_cold_status" -ne 0 ]] || fail "cold check accepted the unresolved name before adding its declaration"
absent_cold_diagnostic="$(grep -F 'error:' "$WORK/name-absent-cold.stderr" | grep -F 'newly_added_name' | tail -n 1 || true)"
[[ -n "$absent_cold_diagnostic" ]] || fail "cold check missed the absent declaration: $(tail -n 8 "$WORK/name-absent-cold.stderr")"
absent_server_count_before="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
send_check 1
absent_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$absent_report" "the absent name"
assert_body_walker_skips "$absent_report" "the absent-name source" 0
absent_name_hits="$(name_lookup_hits_from_report "$absent_report")"
[[ "$absent_name_hits" -eq 0 ]] || fail "fresh absent-name request unexpectedly had prior NameLookup hits: $absent_report"
absent_warm_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'newly_added_name' | tail -n 1 || true)"
absent_warm_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
[[ "$absent_warm_count" -eq "$((absent_server_count_before + 1))" && "$absent_warm_diagnostic" == "$absent_cold_diagnostic" ]] \
    || fail "absent-name diagnostic differs from cold or has wrong multiplicity: cold=[$absent_cold_diagnostic] warm_count=$absent_warm_count warm=[$absent_warm_diagnostic]"

cat >"$SOURCE" <<'EOF'
const newly_added_name: i64 = 7

def main() -> i64:
    return newly_added_name + 0
EOF
declared_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/name-declared-cold.stdout" 2>"$WORK/name-declared-cold.stderr" || declared_cold_status=$?
[[ "$declared_cold_status" -eq 0 ]] || fail "cold check rejected the newly declared constant: $(tail -n 8 "$WORK/name-declared-cold.stderr")"
send_check 0
declared_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$declared_report" "the declaration addition"
declared_warm_missing_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
[[ "$declared_warm_missing_count" -eq 0 ]] \
    || fail "the declared name retained a stale negative diagnostic: $declared_warm_missing_count"

for edit_value in 1 2; do
    cat >"$SOURCE" <<EOF
const newly_added_name: i64 = 7

def main() -> i64:
    return newly_added_name + $edit_value
EOF
    send_check 0
    declared_body_report="$(tail -n 1 "$REPORTS")"
    expected_declared_body_hits=0
    if [[ "$edit_value" -eq 2 ]]; then
        expected_declared_body_hits=1
    fi
    assert_name_lookup_body_edit "$declared_body_report" "body edit after declaration addition $edit_value" "$expected_declared_body_hits"
    declared_body_error_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
    [[ "$declared_body_error_count" -eq 0 ]] \
        || fail "body edit after declaration addition retained a stale diagnostic: $declared_body_error_count"
done

cat >"$SOURCE" <<'EOF'
def main() -> i64:
    return newly_added_name + 0
EOF
removed_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/name-removed-cold.stdout" 2>"$WORK/name-removed-cold.stderr" || removed_cold_status=$?
[[ "$removed_cold_status" -ne 0 ]] || fail "cold check accepted the identifier after removing its declaration"
removed_cold_diagnostic="$(grep -F 'error:' "$WORK/name-removed-cold.stderr" | grep -F 'newly_added_name' | tail -n 1 || true)"
[[ -n "$removed_cold_diagnostic" ]] || fail "cold check missed the removed declaration: $(tail -n 8 "$WORK/name-removed-cold.stderr")"
server_unknown_count_before_remove="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
send_check 1
removed_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$removed_report" "the declaration removal"
removed_warm_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'newly_added_name' | tail -n 1 || true)"
removed_warm_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
[[ "$removed_warm_count" -eq "$((server_unknown_count_before_remove + 1))" && "$removed_warm_diagnostic" == "$removed_cold_diagnostic" ]] \
    || fail "declaration removal differs from cold or has wrong multiplicity: cold=[$removed_cold_diagnostic] warm_count=$removed_warm_count warm=[$removed_warm_diagnostic]"
send_check 1
removed_repeat_report="$(tail -n 1 "$REPORTS")"
[[ "$removed_repeat_report" =~ session=hit([[:space:]]|$) ]] \
    || fail "expected an exact hit for the repeated negative lookup: $removed_repeat_report"
removed_repeat_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'newly_added_name' | tail -n 1 || true)"
removed_repeat_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
[[ "$removed_repeat_count" -eq "$((removed_warm_count + 1))" && "$removed_repeat_diagnostic" == "$removed_cold_diagnostic" ]] \
    || fail "repeated negative lookup differs from cold or has wrong multiplicity: cold=[$removed_cold_diagnostic] warm_count=$removed_repeat_count warm=[$removed_repeat_diagnostic]"

for edit_value in 1 2; do
    cat >"$SOURCE" <<EOF
def main() -> i64:
    return newly_added_name + $edit_value
EOF
    send_check 1
    removed_body_report="$(tail -n 1 "$REPORTS")"
    expected_removed_body_hits=0
    if [[ "$edit_value" -eq 2 ]]; then
        expected_removed_body_hits=1
    fi
    assert_name_lookup_body_edit "$removed_body_report" "negative body edit after declaration removal $edit_value" "$expected_removed_body_hits" zero
    removed_body_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'newly_added_name' | tail -n 1 || true)"
    removed_body_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'newly_added_name' || true)"
    [[ "$removed_body_count" -eq "$((removed_repeat_count + edit_value))" && "$removed_body_diagnostic" == "$removed_cold_diagnostic" ]] \
        || fail "negative body edit after declaration removal differs from cold or has wrong multiplicity: cold=[$removed_cold_diagnostic] warm_count=$removed_body_count warm=[$removed_body_diagnostic]"
done

# A nested module function is indexed under its short name as well as recorded
# as a module member. With no root declaration or import, that one-to-one pair
# is an indexed negative result; declaration changes must invalidate it.
cat >"$SOURCE" <<'EOF'
module Foreign:
    def indexed_name() -> i64:
        return 8

def main() -> i64:
    return indexed_name + 0
EOF
indexed_negative_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/indexed-negative-cold.stdout" 2>"$WORK/indexed-negative-cold.stderr" || indexed_negative_cold_status=$?
[[ "$indexed_negative_cold_status" -ne 0 ]] || fail "cold check accepted the indexed hidden module member"
indexed_negative_cold_diagnostic="$(grep -F 'error:' "$WORK/indexed-negative-cold.stderr" | grep -F 'indexed_name' | tail -n 1 || true)"
[[ -n "$indexed_negative_cold_diagnostic" ]] || fail "cold check missed the indexed negative name: $(tail -n 8 "$WORK/indexed-negative-cold.stderr")"
indexed_server_count_before="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
send_check 1
indexed_negative_seed_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$indexed_negative_seed_report" "the indexed negative name"
[[ "$(name_lookup_hits_from_report "$indexed_negative_seed_report")" -eq 0 ]] \
    || fail "fresh indexed-negative request unexpectedly had a prior NameLookup hit: $indexed_negative_seed_report"
indexed_negative_seed_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'indexed_name' | tail -n 1 || true)"
indexed_negative_seed_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
[[ "$indexed_negative_seed_count" -eq "$((indexed_server_count_before + 1))" && "$indexed_negative_seed_diagnostic" == "$indexed_negative_cold_diagnostic" ]] \
    || fail "indexed-negative seed differs from cold or has wrong multiplicity: cold=[$indexed_negative_cold_diagnostic] warm_count=$indexed_negative_seed_count warm=[$indexed_negative_seed_diagnostic]"

for edit_value in 1 2; do
    cat >"$SOURCE" <<EOF
module Foreign:
    def indexed_name() -> i64:
        return 8

def main() -> i64:
    return indexed_name + $edit_value
EOF
    send_check 1
    indexed_edit_report="$(tail -n 1 "$REPORTS")"
    expected_indexed_edit_hits=0
    if [[ "$edit_value" -eq 2 ]]; then
        expected_indexed_edit_hits=1
    fi
    assert_name_lookup_body_edit "$indexed_edit_report" "indexed negative body edit $edit_value" "$expected_indexed_edit_hits"
    indexed_edit_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'indexed_name' | tail -n 1 || true)"
    indexed_edit_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
    [[ "$indexed_edit_count" -eq "$((indexed_negative_seed_count + edit_value))" && "$indexed_edit_diagnostic" == "$indexed_negative_cold_diagnostic" ]] \
        || fail "indexed negative body edit differs from cold or has wrong multiplicity: cold=[$indexed_negative_cold_diagnostic] warm_count=$indexed_edit_count warm=[$indexed_edit_diagnostic]"
done

# Adding a root declaration makes the module-backed name known; removing it
# restores the indexed negative. Both surface changes must invalidate the result.
cat >"$SOURCE" <<'EOF'
const indexed_name: i64 = 7

module Foreign:
    def indexed_name() -> i64:
        return 8

def main() -> i64:
    return indexed_name + 0
EOF
indexed_visible_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/indexed-visible-cold.stdout" 2>"$WORK/indexed-visible-cold.stderr" || indexed_visible_cold_status=$?
[[ "$indexed_visible_cold_status" -eq 0 ]] || fail "cold check rejected the name after adding its root declaration: $(tail -n 8 "$WORK/indexed-visible-cold.stderr")"
send_check 0
indexed_visible_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$indexed_visible_report" "the indexed-name root declaration addition"
[[ "$(name_lookup_hits_from_report "$indexed_visible_report")" -eq 0 ]] \
    || fail "adding the root declaration reused a stale negative NameLookup result: $indexed_visible_report"
indexed_visible_server_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
[[ "$indexed_visible_server_count" -eq "$((indexed_negative_seed_count + 2))" ]] \
    || fail "adding the root declaration retained an indexed-name diagnostic: seed=$indexed_negative_seed_count after=$indexed_visible_server_count"

for edit_value in 1 2; do
    cat >"$SOURCE" <<EOF
const indexed_name: i64 = 7

module Foreign:
    def indexed_name() -> i64:
        return 8

def main() -> i64:
    return indexed_name + $edit_value
EOF
    send_check 0
    indexed_visible_edit_report="$(tail -n 1 "$REPORTS")"
    expected_indexed_visible_hits=0
    if [[ "$edit_value" -eq 2 ]]; then
        expected_indexed_visible_hits=1
    fi
    assert_name_lookup_body_edit "$indexed_visible_edit_report" "indexed-name body edit after declaration addition $edit_value" "$expected_indexed_visible_hits"
    indexed_visible_edit_error_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
    [[ "$indexed_visible_edit_error_count" -eq "$indexed_visible_server_count" ]] \
        || fail "indexed-name body edit after declaration addition retained a stale diagnostic: before=$indexed_visible_server_count after=$indexed_visible_edit_error_count"
done

cat >"$SOURCE" <<'EOF'
module Foreign:
    def indexed_name() -> i64:
        return 8

def main() -> i64:
    return indexed_name + 0
EOF
indexed_negative_remove_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/indexed-negative-remove-cold.stdout" 2>"$WORK/indexed-negative-remove-cold.stderr" || indexed_negative_remove_status=$?
[[ "$indexed_negative_remove_status" -ne 0 ]] || fail "cold check accepted the indexed negative after removing its root declaration"
indexed_negative_remove_diagnostic="$(grep -F 'error:' "$WORK/indexed-negative-remove-cold.stderr" | grep -F 'indexed_name' | tail -n 1 || true)"
[[ "$indexed_negative_remove_diagnostic" == "$indexed_negative_cold_diagnostic" ]] \
    || fail "root declaration removal cold diagnostic differs: seed=[$indexed_negative_cold_diagnostic] removed=[$indexed_negative_remove_diagnostic]"
indexed_negative_server_count_before_remove="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
send_check 1
indexed_negative_remove_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$indexed_negative_remove_report" "the indexed-name root declaration removal"
[[ "$(name_lookup_hits_from_report "$indexed_negative_remove_report")" -eq 0 ]] \
    || fail "removing the root declaration reused a stale positive NameLookup result: $indexed_negative_remove_report"
indexed_negative_remove_server_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
indexed_negative_remove_warm="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'indexed_name' | tail -n 1 || true)"
[[ "$indexed_negative_remove_server_count" -eq "$((indexed_negative_server_count_before_remove + 1))" && "$indexed_negative_remove_warm" == "$indexed_negative_remove_diagnostic" ]] \
    || fail "root declaration removal differs from cold or has wrong multiplicity: cold=[$indexed_negative_remove_diagnostic] warm_count=$indexed_negative_remove_server_count warm=[$indexed_negative_remove_warm]"

for edit_value in 1 2; do
    cat >"$SOURCE" <<EOF
module Foreign:
    def indexed_name() -> i64:
        return 8

def main() -> i64:
    return indexed_name + $edit_value
EOF
    send_check 1
    indexed_removed_body_report="$(tail -n 1 "$REPORTS")"
    expected_indexed_removed_hits=0
    if [[ "$edit_value" -eq 2 ]]; then
        expected_indexed_removed_hits=1
    fi
    assert_name_lookup_body_edit "$indexed_removed_body_report" "indexed-name body edit after declaration removal $edit_value" "$expected_indexed_removed_hits"
    indexed_removed_body_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | grep -F 'indexed_name' | tail -n 1 || true)"
    indexed_removed_body_count="$(grep -F 'error:' "$WORK/server.stderr" | grep -Fc 'indexed_name' || true)"
    [[ "$indexed_removed_body_count" -eq "$((indexed_negative_remove_server_count + edit_value))" && "$indexed_removed_body_diagnostic" == "$indexed_negative_remove_diagnostic" ]] \
        || fail "indexed-name body edit after declaration removal differs from cold or has wrong multiplicity: cold=[$indexed_negative_remove_diagnostic] warm_count=$indexed_removed_body_count warm=[$indexed_removed_body_diagnostic]"
done

write_valid_source 41 1
send_check 0

# Adding an include changes the source identity and starts a fresh retained snapshot.
# Later body-only edits at that same include path can reuse unaffected function facts.
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
assert_no_graph_restore "$include_seed_report" "the new include surface" 2

# A supported body-only edit at the same include path preserves SourceIdentity
# and declaration surface. The edited include body must scan cold while main
# restores its unchanged function-body facts.
cat >"$INCLUDED" <<'EOF'
def include_helper() -> i64:
    return 41
EOF
send_check 0
include_supported_edit_report="$(tail -n 1 "$REPORTS")"
assert_graph_body_edit "$include_supported_edit_report" "the supported include body edit" 1

# An unresolved call is outside the supported body grammar. This first transition
# still admits the previous cacheable surface: the changed helper cold-scans while
# unchanged main restores. Publication then includes the unsupported body in the
# surface, so recovery from it must cold-fallback.
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
assert_graph_body_edit "$include_edit_report" "the unsupported include transition" 1
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
assert_no_graph_restore "$include_recovery_report" "the recovered include body after an unsupported state" 2

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
    return signature_helper(1)
EOF
signature_cold_status=0
"$STAGE1" -emit check "$SOURCE" >"$WORK/signature-cold.stdout" 2>"$WORK/signature-cold.stderr" || signature_cold_status=$?
[[ "$signature_cold_status" -ne 0 ]] || fail "cold check accepted an argument that no longer matches the edited signature"
signature_cold_diagnostic="$(grep -F 'error:' "$WORK/signature-cold.stderr" | tail -n 1 || true)"
[[ -n "$signature_cold_diagnostic" ]] || fail "cold check reported no diagnostic for the signature edit"
send_check 1
signature_edit_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$signature_edit_report" "the signature edit" 2
signature_warm_diagnostic="$(grep -F 'error:' "$WORK/server.stderr" | tail -n 1 || true)"
[[ "$signature_warm_diagnostic" == "$signature_cold_diagnostic" ]] \
    || fail "signature-edit diagnostic differs from cold: cold=[$signature_cold_diagnostic] warm=[$signature_warm_diagnostic]"

cat >"$SOURCE" <<'EOF'
def signature_helper(value: bool) -> i64:
    return 40

def main() -> i64:
    return signature_helper(true)
EOF
send_check 0
signature_recovery_report="$(tail -n 1 "$REPORTS")"
assert_no_graph_restore "$signature_recovery_report" "the recovered signature edit" 2

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
assert_graph_body_edit "$shifted_report" "the shifted helper edit" 3
[[ "$shifted_report" =~ self_assignment_bodies_reused=2([[:space:]]|$) ]] || fail "expected exactly two complete self-assignment body ranges to reuse on the inserted-line request: $shifted_report"
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
