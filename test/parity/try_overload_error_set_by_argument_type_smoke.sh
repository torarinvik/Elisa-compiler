#!/usr/bin/env bash
# Try propagation should use the overload selected by argument types when two
# same-arity declarations return different error families.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try overload error-set smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_error_set_by_argument_type.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the mismatched selected overload"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L22
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] \
    || fail "Stage0 selected-overload diagnostics changed:\n$stage0_rows\n$stage0_output"
grep -q '^D 1$' <<< "$stage1_output" \
    || fail "Stage1 reported an unexpected diagnostic count:\n$stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] \
    || fail "Stage1 selected-overload diagnostics differ:\n$stage1_rows\n$stage1_output"

# Keep a primitive overload case separate from the i64 parity baseline above.
# This was checked only after the Stage0 freshness gate passed; bool must select
# the bool overload that declares Second::Fault.
BOOL_FIXTURE="$REPO_ROOT/test/repro/try_overload_error_set_by_bool_argument.elisa"
set +e
bool_stage0_output="$("$ELISACORE_BIN" -emit semantic "$BOOL_FIXTURE" 2>&1)"
bool_stage0_status=$?
set -e
[[ "$bool_stage0_status" -ne 0 ]] || fail "Stage0 accepted the mismatched bool-selected overload"
bool_stage0_rows="$(printf '%s\n' "$bool_stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
bool_stage1_output="$("$RPT" < "$BOOL_FIXTURE")"
bool_stage1_rows="$(printf '%s\n' "$bool_stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
bool_expected_rows="$(cat <<'EOF'
L20
EOF
)"
[[ "$bool_stage0_rows" == "$bool_expected_rows" ]] \
    || fail "Stage0 bool-selected diagnostics changed:\n$bool_stage0_rows\n$bool_stage0_output"
grep -q '^D 1$' <<< "$bool_stage1_output" \
    || fail "Stage1 reported an unexpected bool-overload diagnostic count:\n$bool_stage1_output"
[[ "$bool_stage1_rows" == "$bool_expected_rows" ]] \
    || fail "Stage1 bool-selected diagnostics differ:\n$bool_stage1_rows\n$bool_stage1_output"

# A concrete receiver must outrank a generic receiver even when the generic's
# later parameter types would otherwise look like a candidate by arity.
RANK_FIXTURE="$REPO_ROOT/test/repro/try_overload_generic_receiver_rank.elisa"
set +e
rank_stage0_output="$("$ELISACORE_BIN" -emit semantic "$RANK_FIXTURE" 2>&1)"
rank_stage0_status=$?
set -e
[[ "$rank_stage0_status" -eq 0 ]] \
    || fail "Stage0 rejected the concrete-receiver overload call:\n$rank_stage0_output"
rank_stage0_rows="$(printf '%s\n' "$rank_stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
[[ -z "$rank_stage0_rows" ]] \
    || fail "Stage0 reported an unexpected concrete-receiver diagnostic:\n$rank_stage0_rows\n$rank_stage0_output"
rank_stage1_output="$("$RPT" < "$RANK_FIXTURE")"
grep -q '^D 0$' <<< "$rank_stage1_output" \
    || fail "Stage1 did not resolve the concrete receiver overload:\n$rank_stage1_output"
if grep -q 'cannot propagate' <<< "$rank_stage1_output"; then
    fail "Stage1 included the generic overload's error family:\n$rank_stage1_output"
fi

echo "try bool-overload error-set smoke OK: bool selects Second::Fault"
echo "try generic-receiver overload smoke OK: the concrete receiver selects Second::Fault"
echo "try overload error-set smoke OK: argument type selects the matching family"
