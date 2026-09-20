#!/usr/bin/env bash
# Nested module references inside sibling modules stay bound to their own namespace.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-nested-const-collision.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
clang -c -O2 -o "$WORK/profile_hooks.o" "$ROOT/test/parity/profile_hooks.c"

for pair in "stage0:$STAGE0" "stage1:$STAGE1"; do
    name="${pair%%:*}"
    compiler="${pair#*:}"
    "$compiler" -emit obj -O0 -o "$WORK/$name.o" "$ROOT/test/repro/nested_const_module_collision.elisa"
    clang -Wl,-dead_strip -o "$WORK/$name" "$WORK/$name.o" \
        "$WORK/profile_hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
    "$WORK/$name"
done

echo "nested const module collision parity OK"
