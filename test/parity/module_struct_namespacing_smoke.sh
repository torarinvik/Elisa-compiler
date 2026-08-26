#!/usr/bin/env bash
# Stage0/stage1 regression: two modules may each declare a struct of one name.
#
# Struct names shared ONE flat table keyed by bare name, so the second `Work`
# overwrote the first -- `struct literal "Work" is missing field "tally"` on
# stage1, for a program stage0 compiles and runs.
#
# Three lookups in one fixture: the qualified name, a bare name inside a
# module, and a bare name at top level with modules also declaring it.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/module_struct_namespacing.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Each stage is built the way this project actually builds it: the fixture
# INCLUDES elisacore_runtime.elisa, and stage0 emits that runtime into its own
# object (so a bare `cc` links it, and adding build/runtime/elisacore_runtime.o
# would give 40 duplicate symbols), while stage1 does not (so its object alone
# leaves _arena_free unresolved) and its driver script owns the link.
"$STAGE0" -emit obj -O2 -o "$TMP_DIR/stage0.o" "$FIXTURE" >/dev/null 2>&1
cc "$TMP_DIR/stage0.o" -o "$TMP_DIR/stage0"
"$STAGE1" -emit exe -O2 -o "$TMP_DIR/stage1" "$FIXTURE" >/dev/null 2>&1

# A declined function is the failure mode this guards, and stage1 can still
# write an object while declining -- so check the marker, not just the status.
"$STAGE1" -emit llvm -o "$TMP_DIR/stage1.ll" "$FIXTURE" >/dev/null 2>&1
! rg -q '!elisa\.declined' "$TMP_DIR/stage1.ll"

set +e
"$TMP_DIR/stage0"; stage0_status=$?
"$TMP_DIR/stage1"; stage1_status=$?
set -e
test "$stage0_status" -eq 123
test "$stage1_status" -eq 123

echo "module struct namespacing parity OK: stage0 and stage1 return 123"
