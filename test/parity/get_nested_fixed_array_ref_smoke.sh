#!/usr/bin/env bash
# Stage0/stage1 parity regression for nested fixed-array reference inference.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIX="$ROOT/test/repro/get_nested_array_ref.elisa"

fail() { echo "nested-fixed-array-ref smoke FAIL: $1" >&2; exit 1; }

[[ -x "$STAGE1" ]] || { echo "nested-fixed-array-ref smoke SKIP: no stage1 binary at $STAGE1"; exit 0; }
[[ -f "$FIX" ]] || fail "missing fixture: $FIX"

source "$ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

set +e
"$ELISACORE_BIN" -emit obj -O2 -o "$WORK/stage0.o" "$FIX" >"$WORK/stage0.log" 2>&1
stage0_rc=$?
"$STAGE1" -emit obj -O2 -o "$WORK/stage1.o" "$FIX" >"$WORK/stage1.log" 2>&1
stage1_rc=$?
set -e

[[ "$stage0_rc" -ne 0 ]] || fail "stage0 accepted an invalid u8& <- u8[16] initializer"
[[ "$stage1_rc" -ne 0 ]] || fail "stage1 accepted an invalid u8& <- u8[16] initializer"
grep -q 'variable "raw" expects u8&, got u8\[16\]' "$WORK/stage0.log" || fail "stage0 lost the nested-array mismatch: $(cat "$WORK/stage0.log")"
grep -q 'variable "raw" expects non-null reference, got array' "$WORK/stage1.log" || fail "stage1 lost the nested-array mismatch: $(cat "$WORK/stage1.log")"

echo "nested-fixed-array-ref smoke OK: both stages reject the nested array/reference mismatch"
