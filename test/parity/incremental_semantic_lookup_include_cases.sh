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

