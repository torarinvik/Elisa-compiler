#!/usr/bin/env bash
# Codegen + behavior smoke for the self-hosted (stage1) Elisa parser.
#
# Builds the parser end-to-end (lex -> parse), links a tiny C driver, and parses
# a representative fixture covering the constructs the parser currently supports:
# function declarations (with params, return type, indented body), local var
# decls, assignment, if/elif/else chains, structs, and enums with payloads.
#
# Asserts the fixture parses to exactly the expected top-level declaration count
# with ZERO parse errors. This is the parser analogue of the lexer parity check:
# a green run proves the parser both codegens on the platform AND produces a
# structurally correct flat AST (valid contiguous NodeRanges over the node store).
#
# By default this builds the latest compiler from source (via resolve_elisac.sh)
# so the result always reflects current HEAD. Set ELISACORE_BIN to pin a binary.
#
# Usage:
#   test/parity/parser_smoke.sh
#   ELISACORE_BIN=/path/to/elisac test/parity/parser_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

# Always smoke a freshly built compiler (sets ELISACORE_BIN).
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

FIX="$REPO_ROOT/test/parity/parser_smoke.elisa"
[[ -f "$FIX" ]] || { echo "error: missing parser smoke fixture: $FIX" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/driver.c" <<'EOF'
#include "parser_smoke.h"
#include <stdint.h>
#include <stdio.h>

int main(void) {
    const char *src =
        "def add(a: int, b: int) -> int:\n"
        "    sum: int = a\n"
        "    sum <- sum\n"
        "    if a:\n"
        "        return a\n"
        "    elif b:\n"
        "        return b\n"
        "    else:\n"
        "        return sum\n"
        "\n"
        "struct Point:\n"
        "    x: int\n"
        "    y: int\n"
        "\n"
        "enum Color:\n"
        "    Red\n"
        "    Green(shade: int)\n";
    size_t n = 0; while (src[n]) n++;
    uint64_t decls = 0, errors = 0;
    smoke_parse_export((uint8_t *)src, n, &decls, &errors);
    printf("%llu %llu\n", (unsigned long long)decls, (unsigned long long)errors);
    return 0;
}
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/parser_smoke.h" "$FIX" >/dev/null
"$ELISACORE_BIN" -emit obj -permissive -O2 -o "$WORK/parser_smoke.o" "$FIX" >/dev/null

link_flags=(-O2 -I "$WORK" "$WORK/driver.c" "$WORK/parser_smoke.o" -o "$WORK/run")
# See run_parity.sh: non-PIC Elisa objects need dynamic_lookup on macOS, -no-pie on Linux.
[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
[[ "$(uname -s)" == "Linux" ]] && link_flags=(-no-pie "${link_flags[@]}")
clang "${link_flags[@]}"

read -r got_decls got_errors < <("$WORK/run")

EXPECT_DECLS=3
EXPECT_ERRORS=0
if [[ "$got_decls" != "$EXPECT_DECLS" || "$got_errors" != "$EXPECT_ERRORS" ]]; then
	echo "parser smoke FAILED: decls=$got_decls (want $EXPECT_DECLS), errors=$got_errors (want $EXPECT_ERRORS)" >&2
	exit 1
fi

echo "parser smoke OK: decls=$got_decls errors=$got_errors" >&2
