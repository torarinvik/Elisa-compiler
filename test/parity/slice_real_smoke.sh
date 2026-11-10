#!/usr/bin/env bash
# Compile and execute each real stdlib case through both compiler drivers.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/real_std_runtime_cases.sh"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[[ -f "$RUNTIME_OBJ" ]] || { echo "slice_real_smoke FAIL: missing runtime at $RUNTIME_OBJ" >&2; exit 1; }
link_inputs=("$WORK/profile_hooks.o" "$RUNTIME_OBJ")

slice_case() {
    real_std_runtime_case "elisacore_runtime_slice.elisa" "$@" "${link_inputs[@]}"
}

# slice(&da) borrows the darray; len() reports the count via a UFCS generic method.
slice_case len 'def main() -> i64:
    xs: mutable darray[i64] = [10, 20, 12]
    s: Slice[i64] = slice(&xs)
    return s.len().i64() + 39' 42
# get(i) reads element i through the borrowed backing (ref-to-scalar indexing).
slice_case get 'def main() -> i64:
    xs: mutable darray[i64] = [10, 20, 12]
    s: Slice[i64] = slice(&xs)
    return s.get(0.usize()) + s.get(1.usize()) + s.get(2.usize())' 42
# get_unchecked(i) is the unchecked read variant (no bounds branch).
slice_case get_unchecked 'def main() -> i64:
    xs: mutable darray[i64] = [40, 2, 9]
    s: Slice[i64] = slice(&xs)
    return s.get_unchecked(0.usize()) + s.get_unchecked(1.usize())' 42

# split(n, k) returns the k-th of n disjoint bands; its len is the band size.
slice_case split 'def main() -> i64:
    xs: mutable darray[i64] = [1, 2, 3, 4, 5, 6]
    s: Slice[i64] = slice(&xs)
    b: Slice[i64] = s.split(2.usize(), 1.usize())
    return b.len().i64() + 39' 42
# set_unchecked(i, v) WRITES element i through the borrowed backing (ref-to-scalar store);
# the write is observed by a subsequent get and through the source darray.
slice_case set_unchecked 'def main() -> i64:
    xs: mutable darray[i64] = [1, 2, 3, 4]
    s: Slice[i64] = slice(&xs)
    s.set_unchecked(2.usize(), 42)
    return s.get(2.usize())' 42

real_std_runtime_summary "slice_real_smoke"
