#!/usr/bin/env bash
# A payload binder may have the same spelling as a field in the successor state.
# The binder must be live while `-> Next(expr)` is evaluated, while the transition
# store must target the enclosing machine state slot after that binder's scope ends.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT/test/fixtures/machine_transition/shadow.elisa"
INPUT_BIND_SOURCE="$ROOT/test/fixtures/machine_transition/input_bind.elisa"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[[ -x "$STAGE0" ]] || { echo "machine transition shadow smoke SKIP: no stage0"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "machine transition shadow smoke SKIP: no stage1"; exit 0; }
[[ -f "$RUNTIME" ]] || { echo "machine transition shadow smoke SKIP: no runtime object"; exit 0; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-machine-transition-shadow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

run_case() {
    local source="$1"
    local expected="$2"
    local label="$3"

    for optimization in O0 O2; do
    "$STAGE0" -emit obj "-$optimization" -o "$WORK/stage0-$label-$optimization.o" "$source" >/dev/null
    clang -Wl,-undefined,dynamic_lookup -Wl,-dead_strip \
      -o "$WORK/stage0-$label-$optimization" "$WORK/stage0-$label-$optimization.o" "$RUNTIME"

    ELISA_STAGE1_BIN="$STAGE1" ELISA_ALLOW_STALE_STAGE1=1 \
      bash "$ROOT/scripts/elisac_stage1.sh" "-$optimization" \
      -o "$WORK/stage1-$label-$optimization.o" "$source" >/dev/null
    clang -Wl,-undefined,dynamic_lookup -Wl,-dead_strip \
      -o "$WORK/stage1-$label-$optimization" "$WORK/stage1-$label-$optimization.o" "$RUNTIME"

    set +e
    "$WORK/stage0-$label-$optimization"
    stage0_rc=$?
    "$WORK/stage1-$label-$optimization"
    stage1_rc=$?
    set -e

    [[ "$stage0_rc" -eq "$expected" ]] || { echo "machine transition $label smoke FAIL ($optimization): stage0 returned $stage0_rc, expected $expected" >&2; exit 1; }
    [[ "$stage1_rc" -eq "$expected" ]] || { echo "machine transition $label smoke FAIL ($optimization): stage1 returned $stage1_rc, expected $expected" >&2; exit 1; }
    done
}

run_case "$SOURCE" 2 shadow
run_case "$INPUT_BIND_SOURCE" 1 input-bind

echo "machine transition scope smoke OK: payload stores and input binders preserve arm scope at O0/O2"
