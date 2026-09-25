#!/usr/bin/env bash
# Or-pattern accumulator slots must start with valid LLVM i1 handles before branch-specific
# writes; cover enum, sview, and cstr pattern emission at both optimization levels.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/pattern_predicate_initialized.elisa"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[ -x "$STAGE1" ] || { echo "pattern_predicate_initialization FAIL: no stage1 compiler at $STAGE1" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
for level in O0 O2; do
    "$STAGE1" -emit exe "-$level" -o "$WORK/probe-$level" "$FIXTURE"
    set +e
    "$WORK/probe-$level"
    status=$?
    set -e
    if [ "$status" -ne 42 ]; then
        echo "pattern_predicate_initialization FAIL: -$level returned $status, want 42" >&2
        exit 1
    fi
done

echo "pattern_predicate_initialization OK: enum, sview, and cstr OR-patterns at O0/O2"
