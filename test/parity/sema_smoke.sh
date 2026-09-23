#!/usr/bin/env bash
# Semantic smoke for the stage1 symbol-collection pass.
#
# Builds lex -> parse -> collect_symbols end-to-end, links a C driver, and asserts
# that a fixture with a duplicate top-level name and a module body produces the
# expected symbol/duplicate counts and verifies declaration-ID consistency through
# the definition-reference side table. This proves the parsed AST is CONSUMABLE
# (declarations matched, module bodies recursed) and that the semantic result
# survives the region-polymorphic return.
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
    /* 9 source symbols include the duplicate add and a unique target/caller pair.
       Outputs four and five verify declaration and shadowed BindingIds. */
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
        "    return b\n"
        "\n"
        "def target() -> int:\n"
        "    return 7\n"
        "\n"
        "def caller() -> int:\n"
        "    return target()\n"
        "\n"
        "def shadowed(flag: bool) -> int:\n"
        "    value: int = 1\n"
        "    if flag:\n"
        "        value: int = 2\n"
        "        return value\n"
        "    return value\n";
    size_t n = 0; while (src[n]) n++;
    uint64_t syms = 0, dups = 0, stmts = 0, identities = 0, bindings = 0;
    sema_smoke_export((uint8_t *)src, n, &syms, &dups, &stmts, &identities, &bindings);
    printf("%llu %llu %llu %llu %llu\n", (unsigned long long)syms, (unsigned long long)dups, (unsigned long long)stmts, (unsigned long long)identities, (unsigned long long)bindings);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/sema_smoke.h" "$FIX" >/dev/null
"$ELISACORE_BIN" -emit obj -permissive -O2 -o "$WORK/sema_smoke.o" "$FIX" >/dev/null

# The OPTIONAL hooks a real link resolves to the compiler's weak fallbacks. These
# links use -undefined,dynamic_lookup, which turns a missing one into a NULL
# ADDRESS instead of a link error -- so the program built fine and then died with
# SIGSEGV on the arena's first profiler call. Same cause 0b220f1a fixed for
# resolve_smoke and check_self_hostable.
source "$REPO_ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$WORK" "$REPO_ROOT"
link_flags=(-O2 -I "$WORK" "$WORK/driver.c" "$WORK/sema_smoke.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -o "$WORK/run")
[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
[[ "$(uname -s)" == "Linux" ]] && link_flags=(-no-pie "${link_flags[@]}")
clang "${link_flags[@]}"

read -r got_syms got_dups got_stmts got_identities got_bindings < <("$WORK/run")

# 9 source symbols, 1 duplicate, 10 statements across the body fixtures —
# the statement count exercises the typed `stmts` store across the region-poly return.
if [[ "$got_syms" != "9" || "$got_dups" != "1" || "$got_stmts" != "10" || "$got_identities" != "1" || "$got_bindings" != "1" ]]; then
	echo "sema smoke FAILED: symbols=$got_syms (want 9), duplicates=$got_dups (want 1), statements=$got_stmts (want 10), declaration IDs=$got_identities (want 1), binding IDs=$got_bindings (want 1)" >&2
	exit 1
fi

echo "sema smoke OK: symbols=$got_syms duplicates=$got_dups statements=$got_stmts declaration and shadowed binding IDs valid" >&2
