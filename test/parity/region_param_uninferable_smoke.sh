#!/usr/bin/env bash
# A call whose callee grows a reference parameter takes that storage's region as a hidden
# argument. An argument rooted at a local reference with no tracked referent (a cast, a call
# result with no named root) has no region to pass: the function's own region dies at
# return and the callee's growth would dangle. stage0 rejects the call with "cannot infer
# region parameter"; stage1 must print the same line and span. `in perm:` and reference
# parameters bind a region and compile; the `in perm:` fixture runs.
#
# Usage: test/parity/region_param_uninferable_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
FIXTURES="$REPO_ROOT/test/fixtures/region_uninferable"
work="$(mktemp -d "${TMPDIR:-/tmp}/region-param-uninferable.XXXXXX")"
trap 'rm -rf "$work"' EXIT

failures=0
expect_rejection() {
  local fixture="$1" expected="$2" status=0 actual
  "$ELISAC" -emit obj -o "$work/out.o" "$FIXTURES/$fixture.elisa" > "$work/out.txt" 2>&1 || status=$?
  actual="$(grep -v 'warning:' "$work/out.txt" | sed "s|^$FIXTURES/||" || true)"
  if [ "$status" -ne 1 ] || [ "$actual" != "$expected" ]; then
    echo "FAIL $fixture: rc=$status" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    failures=$((failures + 1))
  fi
}
expect_acceptance() {
  local fixture="$1"
  if ! "$ELISAC" -emit obj -o "$work/out.o" "$FIXTURES/$fixture.elisa" > "$work/out.txt" 2>&1; then
    echo "FAIL $fixture: rejected" >&2
    grep -v 'warning:' "$work/out.txt" | head -3 >&2
    failures=$((failures + 1))
  fi
}

expect_rejection reject_cast_reference 'reject_cast_reference.elisa:32:18-19: cannot infer region parameter "__rg_session" for call to "steer"'
expect_rejection reject_cast_reference_field 'reject_cast_reference_field.elisa:31:25-26: cannot infer region parameter "__rg_desk" for call to "raise_window"'
expect_rejection reject_call_reference 'reject_call_reference.elisa:36:14-15: cannot infer region parameter "__rg_session" for call to "steer"'
expect_rejection reject_module_callee 'reject_module_callee.elisa:29:24-25: cannot infer region parameter "__rg_session" for call to "Game.steer"'
expect_acceptance accept_perm_cast_reference
if cc "$work/out.o" "$REPO_ROOT/build/runtime/elisacore_runtime.o" -o "$work/perm" 2> "$work/link.txt"; then
  "$work/perm" || { echo "FAIL accept_perm_cast_reference: exited $?" >&2; failures=$((failures + 1)); }
else
  echo "FAIL accept_perm_cast_reference: does not link" >&2; head -3 "$work/link.txt" >&2; failures=$((failures + 1))
fi
expect_acceptance accept_parameter

[ "$failures" -eq 0 ] || { echo "region param uninferable smoke: $failures failure(s)" >&2; exit 1; }
echo "region param uninferable smoke OK: 4 rejections match stage0, 2 acceptances, perm fixture exits 0"
