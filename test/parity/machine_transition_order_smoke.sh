#!/usr/bin/env bash
# A machine transition installs all successor payloads as one transition. The
# arguments must therefore be evaluated before any scalarized payload slot is
# overwritten: Run(a, b) -> Check(b, a) is a swap, not Run(b, b).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT/test/fixtures/machine_transition/swap.elisa"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[[ -x "$STAGE0" ]] || { echo "machine transition order smoke FAIL: no stage0" >&2; exit 1; }
[[ -x "$STAGE1" ]] || { echo "machine transition order smoke FAIL: no stage1" >&2; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "machine transition order smoke FAIL: no runtime object" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-machine-transition.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for optimization in O0 O2; do
    "$STAGE0" -emit obj "-$optimization" -o "$WORK/stage0-$optimization.o" "$SOURCE" >/dev/null
    clang -Wl,-dead_strip -o "$WORK/stage0-$optimization" "$WORK/stage0-$optimization.o" "$RUNTIME"

    ELISA_STAGE1_BIN="$STAGE1" \
      bash "$ROOT/scripts/elisac_stage1.sh" "-$optimization" -o "$WORK/stage1-$optimization.o" "$SOURCE" >/dev/null
    clang -Wl,-dead_strip -o "$WORK/stage1-$optimization" "$WORK/stage1-$optimization.o" "$RUNTIME"

    set +e
    "$WORK/stage0-$optimization"; stage0_rc=$?
    "$WORK/stage1-$optimization"; stage1_rc=$?
    set -e

    [[ "$stage0_rc" -eq 201 ]] || { echo "machine transition order smoke FAIL ($optimization): stage0 returned $stage0_rc, expected 201" >&2; exit 1; }
    [[ "$stage1_rc" -eq 201 ]] || { echo "machine transition order smoke FAIL ($optimization): stage1 returned $stage1_rc, expected 201" >&2; exit 1; }
done

# A branch-local arrow ends its selected path. The shared suffix adds 2 and targets C
# only on fallthrough; scan(0) instead reaches B, adds 10, and exits with 11.
BRANCH_SOURCE="$ROOT/test/fixtures/machine_transition/branch_transitions.elisa"
for optimization in O0 O2; do
    "$STAGE0" -emit obj "-$optimization" -o "$WORK/branch-stage0-$optimization.o" "$BRANCH_SOURCE" >/dev/null
    clang -Wl,-dead_strip -o "$WORK/branch-stage0-$optimization" "$WORK/branch-stage0-$optimization.o" "$RUNTIME"

    ELISA_STAGE1_BIN="$STAGE1" \
      bash "$ROOT/scripts/elisac_stage1.sh" "-$optimization" -o "$WORK/branch-stage1-$optimization.o" "$BRANCH_SOURCE" >/dev/null
    clang -Wl,-dead_strip -o "$WORK/branch-stage1-$optimization" "$WORK/branch-stage1-$optimization.o" "$RUNTIME"

    set +e
    "$WORK/branch-stage0-$optimization"; branch_stage0_rc=$?
    "$WORK/branch-stage1-$optimization"; branch_stage1_rc=$?
    set -e
    [[ "$branch_stage0_rc" -eq 0 ]] || { echo "machine transition order smoke FAIL ($optimization): stage0 branch result $branch_stage0_rc, expected 0" >&2; exit 1; }
    [[ "$branch_stage1_rc" -eq 0 ]] || { echo "machine transition order smoke FAIL ($optimization): stage1 branch result $branch_stage1_rc, expected 0" >&2; exit 1; }
done

# Statement-position catch arms inside machine arms are void control-flow handlers.
# Stage0's catch-expression arm rule does not describe this statement form, so keep this
# acceptance check Stage1-owned. The fixture combines void handlers with nested
# branch-local transitions; the result proves each path updates exactly once.
VOID_CATCH_SOURCE="$ROOT/test/fixtures/machine_transition/void_catch_in_arm.elisa"
for optimization in O0 O2; do
    ELISA_STAGE1_BIN="$STAGE1" \
      bash "$ROOT/scripts/elisac_stage1.sh" "-$optimization" -o "$WORK/void-catch-stage1-$optimization.o" "$VOID_CATCH_SOURCE" >/dev/null
    clang -Wl,-dead_strip -o "$WORK/void-catch-stage1-$optimization" "$WORK/void-catch-stage1-$optimization.o" "$RUNTIME"

    set +e
    "$WORK/void-catch-stage1-$optimization"; void_catch_rc=$?
    set -e
    [[ "$void_catch_rc" -eq 0 ]] || { echo "machine transition smoke FAIL ($optimization): void catch branch returned $void_catch_rc, expected 0" >&2; exit 1; }
done

echo "machine transition smoke OK: Stage0/Stage1 transitions agree; Stage1 void-catch arms pass at O0/O2"
