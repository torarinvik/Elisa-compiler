#!/usr/bin/env bash
# Regression guard for the stage1 backend's captured-loop/value-if stack leak.
#
# The reproducer used to compile successfully and then exhaust the native stack at runtime.
# The semantic gate must reject it before an object is written. Nearby forms that use the
# same loop machinery but do not contain the unsafe declaration must remain executable.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

BAD="$REPO_ROOT/test/fixtures/rejected_captured_loop_ternary_stack.elisa"
GOOD="$REPO_ROOT/test/fixtures/captured_loop_ternary_neighbors.elisa"
BAD_OBJECT="$WORK/rejected.o"
GOOD_OBJECT="$WORK/neighbors.o"
GOOD_BINARY="$WORK/neighbors"

if bad_output="$("$REPO_ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$BAD_OBJECT" "$BAD" 2>&1)"; then
    echo "captured-loop stack smoke FAILED: unsafe reproducer was accepted" >&2
    exit 1
fi
grep -Fq 'conditional initializer inside a captured loop body' <<<"$bad_output" || {
    echo "captured-loop stack smoke FAILED: missing targeted diagnostic" >&2
    printf '%s\n' "$bad_output" >&2
    exit 1
}
[[ ! -e "$BAD_OBJECT" ]] || {
    echo "captured-loop stack smoke FAILED: rejected source left an object behind" >&2
    exit 1
}

"$REPO_ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$GOOD_OBJECT" "$GOOD"
clang -o "$GOOD_BINARY" "$GOOD_OBJECT"
"$GOOD_BINARY"

echo "captured-loop stack smoke OK: unsafe shape rejected before codegen; neighboring forms run"
