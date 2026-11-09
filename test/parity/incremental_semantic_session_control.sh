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

# Exercise the same storage-region resolution through two generic field projections.
nested_region_output="$WORK/session-nested-region-layout.ll"
if ! "$STAGE1" -emit llvm -O0 -o "$nested_region_output" "$ROOT/test/repro/incremental_session_nested_region_storage.elisa" >"$WORK/session-nested-region-layout.log" 2>&1; then
    fail "Stage1 rejected a same-region store through nested generic fields: $(tail -n 8 "$WORK/session-nested-region-layout.log")"
fi
nested_borrowed_output="$WORK/session-nested-borrowed-source.ll"
if "$STAGE1" -emit llvm -O0 -o "$nested_borrowed_output" "$ROOT/test/repro/incremental_session_nested_borrowed_source.neg.elisa" >"$WORK/session-nested-borrowed-source.log" 2>&1; then
    fail "Stage1 accepted a request-borrowed view stored through nested fields into session storage"
fi
grep -Eq 'short-lived region escapes via store into longer-lived storage|stored into longer-lived region' "$WORK/session-nested-borrowed-source.log" \
    || fail "Stage1 rejected the nested borrowed-source control for an unrelated reason: $(tail -n 8 "$WORK/session-nested-borrowed-source.log")"
[[ ! -e "$nested_borrowed_output" ]] || fail "Stage1 emitted LLVM for a rejected nested borrowed-source control"

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
ELISA_STAGE1_BIN="$STAGE1" \
    ELISA_STAGE1_INCREMENTAL_QUERY_GRAPH=1 \
    ELISA_STAGE1_INCREMENTAL_NAME_LOOKUP_DIRECT=0 \
    ELISA_STAGE1_INCREMENTAL_CACHE_REPORT=1 \
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

# A complete-empty literal body is independent of declaration-surface edits.
# Keep a second literal body and add one new declaration so the graph can prove
# that the old helper stays Green while newly introduced bodies are committed.
write_surface_transition_source() {
    local helper_mode="$1"
    local include_post_broad_surface="${2:-0}"
    : >"$SOURCE"
    if [[ "$helper_mode" == "literal" ]]; then
        cat >>"$SOURCE" <<'EOF'
def helper() -> i64:
    return 41
EOF
    else
        cat >>"$SOURCE" <<'EOF'
def helper() -> i64:
    return source_leaf()
EOF
    fi
    cat >>"$SOURCE" <<'EOF'

def source_leaf() -> i64:
    return 11

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

def unrelated_surface() -> i64:
    return 13
EOF
    if [[ "$include_post_broad_surface" == 1 ]]; then
        cat >>"$SOURCE" <<'EOF'

def post_broad_surface() -> i64:
    return 19
EOF
    fi
}
write_surface_transition_source literal
send_check 0
empty_surface_report="$(tail -n 1 "$REPORTS")"
[[ "$empty_surface_report" =~ source_input_admitted=no([[:space:]]|$) ]] \
    || fail "complete-empty declaration edit unexpectedly admitted SourceInput: $empty_surface_report"
[[ "$empty_surface_report" =~ complete_empty_body_eligible=3([[:space:]]|$) ]] \
    || fail "complete-empty declaration edit classified the wrong bodies: $empty_surface_report"
[[ "$empty_surface_report" =~ complete_empty_body_restored=1([[:space:]]|$) ]] \
    || fail "complete-empty declaration edit did not restore the unchanged helper: $empty_surface_report"
[[ "$empty_surface_report" =~ complete_empty_body_publish_skips=1([[:space:]]|$) ]] \
    || fail "complete-empty declaration edit did not skip the restored helper publication: $empty_surface_report"
[[ "$empty_surface_report" =~ complete_empty_body_commits=2([[:space:]]|$) ]] \
    || fail "complete-empty declaration edit did not commit both new literal bodies: $empty_surface_report"
[[ "$empty_surface_report" =~ function_body_facts_restored=0([[:space:]]|$) ]] \
    || fail "complete-empty declaration edit restored a SourceInput-dependent body: $empty_surface_report"
[[ "$empty_surface_report" =~ cold_body_scans=1([[:space:]]|$) ]] \
    || fail "complete-empty declaration edit did not cold-scan its ordinary call body: $empty_surface_report"

# Exercise both dependency-shape transitions. Literal -> call changes [] to
# [SourceInput], while call -> literal changes it back. In each direction the
# edited body must commit once and unchanged empty siblings must remain reusable.
write_surface_transition_source call
send_check 0
empty_to_broad_report="$(tail -n 1 "$REPORTS")"
[[ "$empty_to_broad_report" =~ source_input_admitted=yes([[:space:]]|$) ]] \
    || fail "empty-to-broad transition failed to admit unchanged SourceInput: $empty_to_broad_report"
[[ "$empty_to_broad_report" =~ complete_empty_body_eligible=2([[:space:]]|$) ]] \
    || fail "empty-to-broad transition classified the wrong bodies: $empty_to_broad_report"
[[ "$empty_to_broad_report" =~ complete_empty_body_restored=2([[:space:]]|$) ]] \
    || fail "empty-to-broad transition failed to restore the unchanged empty siblings: $empty_to_broad_report"
[[ "$empty_to_broad_report" =~ complete_empty_body_publish_skips=2([[:space:]]|$) ]] \
    || fail "empty-to-broad transition did not skip both restored empty siblings: $empty_to_broad_report"
[[ "$empty_to_broad_report" =~ complete_empty_body_commits=0([[:space:]]|$) ]] \
    || fail "empty-to-broad transition unexpectedly committed an empty query: $empty_to_broad_report"

# A surface change while the helper is call-bearing must invalidate both it and
# main, while the empty siblings stay reusable through their dependency-free nodes.
cat >>"$SOURCE" <<'EOF'

def post_broad_surface() -> i64:
    return 19
EOF
send_check 0
post_broad_surface_report="$(tail -n 1 "$REPORTS")"
[[ "$post_broad_surface_report" =~ source_input_admitted=no([[:space:]]|$) ]] \
    || fail "post-broad declaration edit unexpectedly admitted SourceInput: $post_broad_surface_report"
[[ "$post_broad_surface_report" =~ complete_empty_body_eligible=3([[:space:]]|$) ]] \
    || fail "post-broad declaration edit classified the wrong empty bodies: $post_broad_surface_report"
[[ "$post_broad_surface_report" =~ complete_empty_body_restored=2([[:space:]]|$) ]] \
    || fail "post-broad declaration edit failed to restore both old empty bodies: $post_broad_surface_report"
[[ "$post_broad_surface_report" =~ complete_empty_body_publish_skips=2([[:space:]]|$) ]] \
    || fail "post-broad declaration edit did not skip both empty-body publications: $post_broad_surface_report"
[[ "$post_broad_surface_report" =~ complete_empty_body_commits=1([[:space:]]|$) ]] \
    || fail "post-broad declaration edit did not commit its new empty body: $post_broad_surface_report"
[[ "$post_broad_surface_report" =~ function_body_facts_restored=0([[:space:]]|$) ]] \
    || fail "post-broad declaration edit restored SourceInput-dependent bodies: $post_broad_surface_report"
[[ "$post_broad_surface_report" =~ body_query_publish_skips=0([[:space:]]|$) ]] \
    || fail "post-broad declaration edit skipped a SourceInput-dependent publication: $post_broad_surface_report"
[[ "$post_broad_surface_report" =~ cold_body_scans=2([[:space:]]|$) ]] \
    || fail "post-broad declaration edit did not cold-scan both call bodies: $post_broad_surface_report"

write_surface_transition_source literal 1
send_check 0
broad_to_empty_report="$(tail -n 1 "$REPORTS")"
[[ "$broad_to_empty_report" =~ source_input_admitted=yes([[:space:]]|$) ]] \
    || fail "broad-to-empty transition failed to admit unchanged SourceInput: $broad_to_empty_report"
[[ "$broad_to_empty_report" =~ complete_empty_body_eligible=4([[:space:]]|$) ]] \
    || fail "broad-to-empty transition classified the wrong bodies: $broad_to_empty_report"
[[ "$broad_to_empty_report" =~ complete_empty_body_restored=3([[:space:]]|$) ]] \
    || fail "broad-to-empty transition failed to restore the unchanged empty siblings: $broad_to_empty_report"
[[ "$broad_to_empty_report" =~ complete_empty_body_publish_skips=3([[:space:]]|$) ]] \
    || fail "broad-to-empty transition did not skip both restored empty siblings: $broad_to_empty_report"
[[ "$broad_to_empty_report" =~ complete_empty_body_commits=1([[:space:]]|$) ]] \
    || fail "broad-to-empty transition did not recommit the literal helper: $broad_to_empty_report"

# A second declaration change after the helper returns to the empty dependency
# shape proves that the previous SourceInput edge was removed when it was recommitted.
cat >>"$SOURCE" <<'EOF'

def post_transition_surface() -> i64:
    return 17
EOF
send_check 0
post_transition_surface_report="$(tail -n 1 "$REPORTS")"
[[ "$post_transition_surface_report" =~ source_input_admitted=no([[:space:]]|$) ]] \
    || fail "post-transition declaration edit unexpectedly admitted SourceInput: $post_transition_surface_report"
[[ "$post_transition_surface_report" =~ complete_empty_body_eligible=5([[:space:]]|$) ]] \
    || fail "post-transition declaration edit classified the wrong empty bodies: $post_transition_surface_report"
[[ "$post_transition_surface_report" =~ complete_empty_body_restored=4([[:space:]]|$) ]] \
    || fail "post-transition declaration edit did not retain all old empty bodies: $post_transition_surface_report"
[[ "$post_transition_surface_report" =~ complete_empty_body_publish_skips=4([[:space:]]|$) ]] \
    || fail "post-transition declaration edit did not skip all old empty-body publications: $post_transition_surface_report"
[[ "$post_transition_surface_report" =~ complete_empty_body_commits=1([[:space:]]|$) ]] \
    || fail "post-transition declaration edit did not commit its new empty body: $post_transition_surface_report"
[[ "$post_transition_surface_report" =~ function_body_facts_restored=0([[:space:]]|$) ]] \
    || fail "post-transition declaration edit restored a SourceInput-dependent body: $post_transition_surface_report"
[[ "$post_transition_surface_report" =~ body_query_publish_skips=0([[:space:]]|$) ]] \
    || fail "post-transition declaration edit skipped a SourceInput-dependent publication: $post_transition_surface_report"
[[ "$post_transition_surface_report" =~ cold_body_scans=1([[:space:]]|$) ]] \
    || fail "post-transition declaration edit did not cold-scan its ordinary call body: $post_transition_surface_report"

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

source "$ROOT/test/parity/incremental_semantic_lookup_include_cases.sh"

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
[[ "$lint_warning_count" -eq 8 ]] || fail "expected the current self-assignment warning on all eight requests containing that function, got $lint_warning_count"
captured_lint_warning_count="$(grep -Fc 'assignment to "state" has no effect: target and value are identical' "$WORK/server.stderr" || true)"
[[ "$captured_lint_warning_count" -eq 8 ]] || fail "expected the captured-loop warning on all eight requests containing that function, got $captured_lint_warning_count"
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
value_line9_count="$(count_warning_at value 9)"
state_line12_count="$(count_warning_at state 12)"
state_line13_count="$(count_warning_at state 13)"
state_line15_count="$(count_warning_at state 15)"
[[ "$value_line6_count" -eq 2 && "$value_line7_count" -eq 1 && "$value_line9_count" -eq 5 ]] || fail "unexpected straight-line warning anchors after adding complete-empty surface cases: $value_line6_count/$value_line7_count/$value_line9_count"
[[ "$state_line12_count" -eq 2 && "$state_line13_count" -eq 1 && "$state_line15_count" -eq 5 ]] || fail "unexpected captured-loop warning anchors after adding complete-empty surface cases: $state_line12_count/$state_line13_count/$state_line15_count"
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
