#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Regression: in `X if COND else Y`, a subscript ending COND must not take the `else` as a
# subscript default (`a[i] else <value>`), which left the conditional without an alternative
# and made the backend decline the function.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
FIXTURE="$ROOT/test/repro/ternary_condition_subscript.elisa"

ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/program.o" "$FIXTURE"
clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/program" "$WORK/program.o" "$RUNTIME"
"$WORK/program" || { echo "ternary-condition subscript smoke FAIL: program exited $?" >&2; exit 1; }

echo "ternary-condition subscript smoke OK"
