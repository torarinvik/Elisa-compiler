#!/usr/bin/env bash
# Try overload ranking must compare nominal owner identity, not bare type spelling.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
  echo "try same-named module types smoke FAIL: $1" >&2
  exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_private_same_named_module_types.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted private generic winners for same-named nominal types"
[[ $(grep -cF 'is private to module "NamedProvider"' <<< "$stage0_output") == 2 ]] \
  || fail "Stage0 did not reject both direct and cached private winners: $stage0_output"
if grep -qF 'try requires a fallible expression' <<< "$stage0_output"; then
  fail "Stage0 cascaded `try` diagnostics after the invalid private call: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
[[ $(grep -cF 'is private to module "NamedProvider"' <<< "$stage1_output") == 2 ]] \
  || fail "Stage1 confused same-spelled nominal types in direct or cached Try ranking: $stage1_output"
if grep -qF 'try requires a fallible expression' <<< "$stage1_output"; then
  fail "Stage1 cascaded `try` diagnostics after the invalid private call: $stage1_output"
fi
# The reporter reads stdin and reports logical lines, not a file path. Check both
# call sites explicitly so a duplicate diagnostic at one site cannot mask another.
for line in 24 27; do
  grep -qF "L$line \"NamedProvider.inspect\" is private to module \"NamedProvider\"" <<< "$stage1_output" \
    || fail "Stage1 missed the private winner at line $line: $stage1_output"
done

echo "try same-named module types smoke OK"
