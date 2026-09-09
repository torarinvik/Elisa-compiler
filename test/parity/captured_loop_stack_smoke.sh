#!/usr/bin/env bash
# Regression guard for the stage1 backend's captured-loop/value-if stack leak.
#
# The reproducer used to compile successfully and then exhaust the native stack at runtime.
# It must now compile and run, proving that value-if result storage is frame-stable. Nearby
# forms using the same loop machinery remain executable as well.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

REGRESSION="$REPO_ROOT/test/fixtures/captured_loop_ternary_stack_regression.elisa"
GOOD="$REPO_ROOT/test/fixtures/captured_loop_ternary_neighbors.elisa"
REGRESSION_OBJECT="$WORK/regression.o"
REGRESSION_BINARY="$WORK/regression"
GOOD_OBJECT="$WORK/neighbors.o"
GOOD_BINARY="$WORK/neighbors"

"$REPO_ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$REGRESSION_OBJECT" "$REGRESSION"
clang -o "$REGRESSION_BINARY" "$REGRESSION_OBJECT"
"$REGRESSION_BINARY"

"$REPO_ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$GOOD_OBJECT" "$GOOD"
clang -o "$GOOD_BINARY" "$GOOD_OBJECT"
"$GOOD_BINARY"

echo "captured-loop stack smoke OK: former stack leak runs safely; neighboring forms run"
