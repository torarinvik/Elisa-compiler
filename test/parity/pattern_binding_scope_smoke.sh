#!/usr/bin/env bash
# Regression for pattern-binding scope and dominance. Match arms that reuse a binding name
# must write one shared entry-block slot; otherwise a post-match read can load an arm-local
# alloca that does not dominate the join (or silently select the wrong shadowing binding).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
PROFILE="$ROOT/test/parity/profile_hooks.c"
FIXTURE="$ROOT/test/repro/pattern_binding_scope.elisa"

[[ -x "$STAGE1" ]] || { echo "pattern-binding scope smoke SKIP: no stage1 at $STAGE1" >&2; exit 0; }
[[ -f "$RUNTIME" ]] || { echo "pattern-binding scope smoke SKIP: no runtime object at $RUNTIME" >&2; exit 0; }

clang -c -O2 -o "$WORK/profile_hooks.o" "$PROFILE"

run_stage0() {
    "$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE"
}

run_stage1() {
    ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/stage1.o" "$FIXTURE"
}

run_binary() {
    local tag="$1"
    clang -Wl,-dead_strip -o "$WORK/$tag" "$WORK/$tag.o" "$RUNTIME" "$WORK/profile_hooks.o"
    set +e
    "$WORK/$tag"
    local actual=$?
    set -e
    [[ "$actual" -eq 63 ]] || {
        echo "pattern-binding scope smoke FAIL: $tag returned $actual, expected 63" >&2
        exit 1
    }
}

run_stage0
run_binary stage0
run_stage1
run_binary stage1

echo "pattern-binding scope smoke OK: is/catch/match bindings agree and post-match loads dominate"
