#!/usr/bin/env bash
# Lambda raise checking must use the overload selected from the call arguments.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/lambda_raise_overloaded_callee.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
if [[ "$stage0_status" -eq 0 ]]; then
    echo "overloaded Lambda raise smoke expected Stage0 to reject the mismatched callback" >&2
    exit 1
fi
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: raise cannot propagate tag.*$#L\1#p' \
    | LC_ALL=C sort)"
output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$output" | sed -E -n 's/^  (L[0-9]+) raise cannot propagate tag.*/\1/p' | LC_ALL=C sort)"
expected_rows=$'L16\nL25\nL33\nL36\nL45'
if [[ "$stage0_rows" != "$expected_rows" ]] \
    || [[ "$stage1_rows" != "$expected_rows" ]] \
    || ! grep -q '^D 5$' <<< "$output"; then
    printf 'overloaded Lambda raise smoke did not match the expected call sites:\nStage0 rows: %s\nStage1 rows: %s\nStage0 output:\n%s\nStage1 output:\n%s\n' \
        "$stage0_rows" "$stage1_rows" "$stage0_output" "$output" >&2
    exit 1
fi

shadow_output="$("$RPT" < "$REPO_ROOT/test/repro/lambda_raise_overload_shadow.elisa")"
if ! grep -q '^P 0$' <<< "$shadow_output" || grep -q 'raise cannot propagate tag' <<< "$shadow_output"; then
    printf 'overloaded Lambda raise smoke resolved a shadowed module root:\n%s\n' "$shadow_output" >&2
    exit 1
fi
bare_shadow_output="$("$RPT" < "$REPO_ROOT/test/repro/lambda_raise_overload_bare_shadow.elisa")"
if ! grep -q '^P 0$' <<< "$bare_shadow_output" || grep -q 'raise cannot propagate tag' <<< "$bare_shadow_output"; then
    printf 'overloaded Lambda raise smoke resolved a shadowed bare callable:\n%s\n' "$bare_shadow_output" >&2
    exit 1
fi

mixed_fixture="$REPO_ROOT/test/repro/lambda_raise_overload_mixed_returns.elisa"
set +e
mixed_stage0="$("$ELISACORE_BIN" -emit semantic "$mixed_fixture" 2>&1)"
mixed_status=$?
set -e
mixed_rows="$(printf '%s\n' "$mixed_stage0" | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: raise cannot propagate tag.*$#L\1#p' | LC_ALL=C sort)"
mixed_stage1="$("$RPT" < "$mixed_fixture")"
if [[ "$mixed_status" -eq 0 || "$mixed_rows" != 'L14' ]] || ! grep -q '^P 0$' <<< "$mixed_stage1" \
    || ! grep -q '^D 1$' <<< "$mixed_stage1" || ! grep -q '^  L14 raise cannot propagate tag' <<< "$mixed_stage1"; then
    printf 'mixed fallible and infallible overloads disagree:\nStage0:\n%s\nStage1:\n%s\n' "$mixed_stage0" "$mixed_stage1" >&2
    exit 1
fi

callback_report="$("$RPT" < "$REPO_ROOT/test/repro/lambda_raise_callback_parameters.elisa")"
if ! grep -q '^P 0$' <<< "$callback_report" || ! grep -q '^D 3$' <<< "$callback_report" \
    || ! grep -q '^  L10 raise cannot propagate tag' <<< "$callback_report" \
    || ! grep -q '^  L12 raise cannot propagate tag' <<< "$callback_report" \
    || ! grep -q '^  L16 raise cannot propagate tag' <<< "$callback_report"; then
    printf 'lambda callback error sets were not checked independently:\n%s\n' "$callback_report" >&2
    exit 1
fi

infallible_report="$("$RPT" < "$REPO_ROOT/test/repro/lambda_raise_infallible_callback.elisa")"
if ! grep -q '^P 0$' <<< "$infallible_report" || ! grep -q '^D 1$' <<< "$infallible_report" \
    || ! grep -q '^  L6 raise requires the current function to return an error union' <<< "$infallible_report"; then
    printf 'lambda raise was not rejected for an infallible callback:\n%s\n' "$infallible_report" >&2
    exit 1
fi

callee_report="$("$RPT" < "$REPO_ROOT/test/repro/lambda_raise_infallible_callee.elisa")"
if ! grep -q '^P 0$' <<< "$callee_report" || ! grep -q '^D 3$' <<< "$callee_report" \
    || ! grep -q '^  L10 raise cannot propagate tag' <<< "$callee_report" \
    || ! grep -q '^  L14 raise requires the current function to return an error union' <<< "$callee_report" \
    || ! grep -q '^  L23 raise cannot propagate tag' <<< "$callee_report"; then
    printf 'infallible callees did not preserve their callback error contracts:\n%s\n' "$callee_report" >&2
    exit 1
fi

echo "overloaded Lambda raise smoke OK"
