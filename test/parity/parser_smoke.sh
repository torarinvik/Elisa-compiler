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
#include <stdlib.h>

static uint8_t *slurp(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = (uint8_t *)malloc((size_t)n + 1);
    if (!b) { fclose(f); return NULL; }
    if (fread(b, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(b); return NULL; }
    fclose(f); b[n] = 0; *out_len = (size_t)n; return b;
}

int main(int argc, char **argv) {
    /* No args: the focused fixture (asserted decls/errors). */
    if (argc < 2) {
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
    /* With file args: parse each and print "<total_errors> <file_count>" — the
       self-parse check (the stage1 frontend must parse its own source cleanly). */
    uint64_t total_errors = 0; int files = 0;
    for (int i = 1; i < argc; i++) {
        size_t n = 0; uint8_t *s = slurp(argv[i], &n);
        if (!s) { fprintf(stderr, "read failed: %s\n", argv[i]); return 3; }
        uint64_t d = 0, e = 0;
        smoke_parse_export(s, n, &d, &e);
        if (e) fprintf(stderr, "  %s: %llu errors\n", argv[i], (unsigned long long)e);
        total_errors += e; files++;
        free(s);
    }
    printf("%llu %d\n", (unsigned long long)total_errors, files);
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

# Self-parse: the stage1 frontend must parse its OWN source (the whole lexer +
# parser) with zero parse errors. This is the dogfooding regression guard — any
# grammar regression that breaks a real frontend file fails here.
FRONTEND_FILES=()
for f in "$REPO_ROOT"/src/lexer/*.elisa "$REPO_ROOT"/src/parser/*.elisa; do
	[[ -f "$f" ]] && FRONTEND_FILES+=("$f")
done
if [[ ${#FRONTEND_FILES[@]} -gt 0 ]]; then
	read -r self_errors self_files < <("$WORK/run" "${FRONTEND_FILES[@]}")
	if [[ "$self_errors" != "0" ]]; then
		echo "parser self-parse FAILED: $self_errors parse errors across $self_files frontend files (want 0)" >&2
		exit 1
	fi
	echo "parser self-parse OK: 0 errors across $self_files frontend files" >&2
fi

# Stdlib parse: the stage1 parser must also parse the whole vendored standard
# library with zero errors. Together with the self-parse above this guards the
# full parser grammar against regressions on real, idiomatic Elisa source.
STD_FILES=()
for f in "$REPO_ROOT"/elisacore_std/*.elisa; do
	[[ -f "$f" ]] && STD_FILES+=("$f")
done
if [[ ${#STD_FILES[@]} -gt 0 ]]; then
	read -r std_errors std_files < <("$WORK/run" "${STD_FILES[@]}")
	if [[ "$std_errors" != "0" ]]; then
		echo "parser stdlib-parse FAILED: $std_errors parse errors across $std_files stdlib files (want 0)" >&2
		exit 1
	fi
	echo "parser stdlib-parse OK: 0 errors across $std_files stdlib files" >&2
fi
