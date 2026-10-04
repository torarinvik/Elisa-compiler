#!/usr/bin/env bash
# Fuzz F18: a `T&` struct field / `darray[T&]` element read in value position used to
# produce invalid IR (and, per the fuzz run, SIGSEGVing programs) through the real driver.
# Builds each repro with BOTH compilers via `-emit obj` at -O0 and -O2, links, runs, and
# requires equal exit codes (82 and 133 — the empty darray read traps on the bounds check).
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
S1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
S0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
RT="$ROOT/build/runtime/elisacore_runtime.o"
for b in "$S1" "$S0"; do [ -x "$b" ] || { echo "ref_value_read_driver FAIL: missing $b" >&2; exit 1; }; done
[ -f "$RT" ] || { echo "ref_value_read_driver FAIL: no runtime object" >&2; exit 1; }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
for case in "ref_field_into_darray_elem 82" "ref_darray_empty_index_arith 133"; do
    set -- $case; name=$1; want=$2
    for O in -O0 -O2; do
        "$S1" -emit obj $O -o "$T/s1.o" "$ROOT/test/repro/$name.elisa" 2>"$T/err" || { echo "  FAIL $name $O: stage1 rejected: $(head -1 "$T/err")"; fail=1; continue; }
        clang -o "$T/s1" "$T/s1.o" "$RT" 2>/dev/null || { echo "  FAIL $name $O: link"; fail=1; continue; }
        "$T/s1"; got=$?
        "$S0" -emit obj $O -o "$T/s0.o" "$ROOT/test/repro/$name.elisa" 2>/dev/null && clang -o "$T/s0" "$T/s0.o" "$RT" 2>/dev/null
        "$T/s0"; ref=$?
        if [ "$got" -ne "$want" ] || [ "$ref" -ne "$want" ]; then echo "  FAIL $name $O: stage1=$got stage0=$ref want=$want"; fail=1; fi
    done
done 2>/dev/null
[ "$fail" -eq 0 ] || { echo "ref_value_read_driver FAILED" >&2; exit 1; }
echo "ref_value_read_driver OK: 2 programs x 2 opt levels match stage0"
