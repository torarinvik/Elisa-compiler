#!/usr/bin/env bash
# Interned type-table smoke (Phase C foundation, backlog items 92-94/96).
#
# Builds lex -> parse -> annotation_type_id end-to-end, links a C driver, and asserts
# every structural check in the fixture passes: tuple/container/optional/ref rows,
# element round-trips, fixed-array modeling, nesting, and intern dedup (TypeId
# equality == structural type equality).
#
# Builds the latest compiler from source via resolve_elisac.sh unless ELISACORE_BIN
# is pinned.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

FIX="$REPO_ROOT/test/parity/type_table_smoke.elisa"
[[ -f "$FIX" ]] || { echo "error: missing type table smoke fixture: $FIX" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/driver.c" <<'EOF'
#include "type_table_smoke.h"
#include <stdint.h>
#include <stdio.h>

int main(void) {
    const char *src =
        "def probe(p: dict[cstr, i64], q: (first: i64, second: i64)) -> void:\n"
        "    a: (first: i64, second: i64) = (1, 2)\n"
        "    b: darray[i64] = []\n"
        "    c: bool? = null\n"
        "    d: u8& = zeroed\n"
        "    e: dict[cstr, i64] = {}\n"
        "    f: i64[3] = [1, 2, 3]\n"
        "    g: darray[i64]? = null\n";
    size_t n = 0; while (src[n]) n++;
    uint64_t passed = 0, total = 0;
    type_table_smoke_export((uint8_t *)src, n, &passed, &total);
    printf("%llu %llu\n", (unsigned long long)passed, (unsigned long long)total);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/type_table_smoke.h" "$FIX" >/dev/null
"$ELISACORE_BIN" -emit obj -O2 -o "$WORK/type_table_smoke.o" "$FIX" >/dev/null

clang -O2 -I "$WORK" "$WORK/driver.c" "$WORK/type_table_smoke.o" -o "$WORK/run"

OUT="$("$WORK/run")"
read -r PASSED TOTAL <<<"$OUT"

# 11 checks in the fixture; every one must pass, and the probe must be found at all.
if [[ "$TOTAL" != "11" || "$PASSED" != "$TOTAL" ]]; then
  echo "type_table_smoke FAILED: passed=$PASSED total=$TOTAL (expected 11/11)" >&2
  exit 1
fi
echo "type_table_smoke OK: $PASSED/$TOTAL structural checks"
