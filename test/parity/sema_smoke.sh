#!/usr/bin/env bash
# Semantic smoke for the stage1 symbol-collection pass.
#
# Builds lex -> parse -> collect_symbols end-to-end, links a C driver, and asserts
# that a fixture with a duplicate top-level name and a module body produces the
# expected symbol count and duplicate count. This proves the parsed AST is
# CONSUMABLE (declarations matched, module bodies recursed) and that the semantic
# result survives the region-polymorphic return.
#
# Builds the latest compiler from source via resolve_elisac.sh unless ELISACORE_BIN
# is pinned.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

FIX="$REPO_ROOT/test/parity/sema_smoke.elisa"
[[ -f "$FIX" ]] || { echo "error: missing sema smoke fixture: $FIX" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/driver.c" <<'EOF'
#include "sema_smoke.h"
#include <stdint.h>
#include <stdio.h>

int main(void) {
    /* 6 symbols: add (Func), P (Struct), M (Module), helper (Func, in M),
       K (Const, in M), add (Func, duplicate). 1 duplicate (the 2nd add). */
    const char *src =
        "def add(a: int) -> int:\n"
        "    return a\n"
        "\n"
        "struct P:\n"
        "    x: int\n"
        "\n"
        "module M:\n"
        "    def helper() -> int:\n"
        "        return 1\n"
        "    const K: int = 5\n"
        "\n"
        "def add(b: int) -> int:\n"
        "    return b\n";
    size_t n = 0; while (src[n]) n++;
    uint64_t syms = 0, dups = 0;
    sema_smoke_export((uint8_t *)src, n, &syms, &dups);
    printf("%llu %llu\n", (unsigned long long)syms, (unsigned long long)dups);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/sema_smoke.h" "$FIX" >/dev/null
"$ELISACORE_BIN" -emit obj -permissive -O2 -o "$WORK/sema_smoke.o" "$FIX" >/dev/null

link_flags=(-O2 -I "$WORK" "$WORK/driver.c" "$WORK/sema_smoke.o" -o "$WORK/run")
[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
[[ "$(uname -s)" == "Linux" ]] && link_flags=(-no-pie "${link_flags[@]}")
clang "${link_flags[@]}"

read -r got_syms got_dups < <("$WORK/run")

if [[ "$got_syms" != "6" || "$got_dups" != "1" ]]; then
	echo "sema smoke FAILED: symbols=$got_syms (want 6), duplicates=$got_dups (want 1)" >&2
	exit 1
fi

echo "sema smoke OK: symbols=$got_syms duplicates=$got_dups" >&2
