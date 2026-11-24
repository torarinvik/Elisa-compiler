#!/usr/bin/env bash
# `dst.extend(make())` copies a call's elements into a parameter's storage. The call is bound
# to the parameter's region (the callee takes it as a hidden argument), so nothing escapes,
# whatever the element type: stage0 accepts every such extend and so must stage1, and the
# programs must run. Extending with a LOCAL container of references does escape; stage1 must
# print stage0's line and span.
#
# Usage: test/parity/extend_escape_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
FIXTURES="$REPO_ROOT/test/fixtures/extend_escape"
RUNTIME="$REPO_ROOT/build/runtime/elisacore_runtime.o"
work="$(mktemp -d "${TMPDIR:-/tmp}/extend-escape.XXXXXX")"
trap 'rm -rf "$work"' EXIT

failures=0
fail() { echo "FAIL $1" >&2; failures=$((failures + 1)); }
expect_run() {
  local fixture="$1"
  if ! "$ELISAC" -emit obj -o "$work/$fixture.o" "$FIXTURES/$fixture.elisa" > "$work/out.txt" 2>&1; then
    fail "$fixture: rejected: $(grep -v 'warning:' "$work/out.txt" | head -1 || true)"
  elif ! cc "$work/$fixture.o" "$RUNTIME" -o "$work/$fixture" 2> "$work/link.txt"; then
    fail "$fixture: does not link"
  elif ! "$work/$fixture"; then
    fail "$fixture: exited $?"
  fi
}
expect_rejection() {
  local fixture="$1" expected="$2" status=0 actual
  "$ELISAC" -emit obj -o "$work/out.o" "$FIXTURES/$fixture.elisa" > "$work/out.txt" 2>&1 || status=$?
  actual="$(grep -v 'warning:' "$work/out.txt" | sed "s|^$FIXTURES/||" || true)"
  [ "$status" -eq 1 ] && [ "$actual" == "$expected" ] || fail "$fixture: rc=$status
  expected: $expected
  actual:   $actual"
}

for fixture in accept_returned_bytes accept_returned_rows accept_returned_views accept_two_receivers; do
  expect_run "$fixture"
done
expect_rejection reject_local_rows 'reject_local_rows.elisa:9:23-27: value in region "<inferred>" is stored into longer-lived region "__rg_buffer"; region "<inferred>" is freed first, leaving a dangling reference. Copy it into region "__rg_buffer" (or a region that outlives "__rg_buffer") before storing'

[ "$failures" -eq 0 ] || { echo "extend escape smoke: $failures failure(s)" >&2; exit 1; }
echo "extend escape smoke OK: 4 extends of returned darrays run, the local-rows extend matches stage0"
