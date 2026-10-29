#!/usr/bin/env bash
# Check signed quotient/remainder behavior across the optimized pipeline.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
COMPILER="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-divrem.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/probe.elisa" <<'ELISA'
def divrem_impl(a: i64, b: i64) -> i64:
    q: i64 = a / b
    r: i64 = a % b
    return q + r
export fn divrem_probe(a: i64, b: i64) -> i64 = divrem_impl
ELISA
cat > "$WORK/check.c" <<'C'
#include <stdint.h>
#include <limits.h>
extern int64_t divrem_probe(int64_t, int64_t);
int main(void) {
    int64_t a[] = {INT64_MIN, -1001, -99, -1, 0, 1, 99, 1001, INT64_MAX};
    int64_t b[] = {-17, -3, -2, -1, 1, 2, 3, 17};
    for (unsigned i = 0; i < sizeof(a)/sizeof(*a); i++) {
        for (unsigned j = 0; j < sizeof(b)/sizeof(*b); j++) {
            if (a[i] == INT64_MIN && b[j] == -1) continue;
            int64_t q = a[i] / b[j], r = a[i] % b[j];
            if ((r > 0 && q > INT64_MAX-r) || (r < 0 && q < INT64_MIN-r)) continue;
            if (divrem_probe(a[i], b[j]) != q+r) return 1;
        }
    }
    return 0;
}
C
for level in 0 3; do
    "$COMPILER" "-O$level" -emit obj -o "$WORK/probe.o" "$WORK/probe.elisa"
    "${CC:-cc}" "$WORK/check.c" "$WORK/probe.o" -o "$WORK/check"
    "$WORK/check"
done
echo 'signed division and remainder pipeline: PASS'
