#!/usr/bin/env bash
# Stage1 regression: copies of a ~140 KB aggregate (fixed array of structs of fixed
# arrays) through an optional and back must lower to llvm.memmove/memcpy, never a
# first-class `load %T` / `store %T`. SelectionDAG scalarizes those into tens of
# thousands of nodes and goes quadratic: -O2 of this fixture used to exhaust the 4 GB
# stage1 memory guard after minutes; with the copies lowered it takes well under a second.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/large_aggregate_copy_memcpy.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
fail() { echo "large-aggregate-copy-memcpy smoke FAIL: $1" >&2; exit 1; }

# 1. Runs correctly.
"$STAGE1" -emit exe -o "$TMP_DIR/repro" "$FIXTURE" >"$TMP_DIR/build.err" 2>&1 \
  || fail "exe build failed: $(cat "$TMP_DIR/build.err")"
set +e
"$TMP_DIR/repro"
status=$?
set -e
test "$status" -eq 0 || fail "fixture exited $status"

# 2. -O0 IR has no first-class load/store of the large types (bare or optional-wrapped).
"$STAGE1" -emit llvm -o "$TMP_DIR/repro.ll" "$FIXTURE" >"$TMP_DIR/llvm.err" 2>&1 \
  || fail "-emit llvm failed: $(cat "$TMP_DIR/llvm.err")"
if grep -nE '(= load|store) (\{ i1, )?%Big\.(History|Stack)\b' "$TMP_DIR/repro.ll"; then
  fail "first-class load/store of a large aggregate survived in the emitted IR"
fi
grep -qE 'call void @llvm\.mem(move|cpy)\.' "$TMP_DIR/repro.ll" || fail "no memmove/memcpy emitted"

# 3. -O2 object build finishes quickly (it ran for minutes before the fix).
start=$SECONDS
timeout 60 "$STAGE1" -O2 -emit obj -o "$TMP_DIR/repro.o" "$FIXTURE" >"$TMP_DIR/o2.err" 2>&1 \
  || fail "-O2 build failed or exceeded 60s: $(cat "$TMP_DIR/o2.err")"
test -s "$TMP_DIR/repro.o" || fail "-O2 object missing"

echo "large aggregate copy memcpy smoke OK ($((SECONDS - start))s at -O2)"
