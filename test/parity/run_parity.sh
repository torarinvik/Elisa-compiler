#!/usr/bin/env bash
# Cross-repo lexer parity: stage1 (this repo's Elisa lexer) vs stage0 (Elisa-core).
#
# For each corpus file we compute two token-kind checksums and require they match:
#   * stage1: the self-hosted Elisa lexer, compiled to a native checksum harness.
#   * stage0: `elisacore -emit tokens <file>` (the Go lexer oracle), JSON .checksum.
#
# Inputs must be STANDALONE .elisa files (no `include` directives): the Elisa
# harness lexes raw file bytes, while `-emit tokens` lexes include-expanded
# source — they coincide only when there are no includes.
#
# Resolve Elisa-core via $ELISA_CORE (default: conventional sibling path).
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
ELISACORE_BIN="${ELISACORE_BIN:-$ELISA_CORE/bin/elisacore}"

FIXTURE="$REPO_ROOT/test/fixtures/frontend_lexer.elisa"
SHIMS="$REPO_ROOT/test/fixtures/frontend_lexer_runtime_shims.c"

for tool in "$ELISACORE_BIN" clang; do
	command -v "$tool" >/dev/null 2>&1 || [[ -x "$tool" ]] || { echo "error: missing $tool" >&2; exit 2; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

echo "building stage1 lexer harness…"
"$ELISACORE_BIN" -emit header -o "$WORK/frontend_lexer.h" "$FIXTURE"
"$ELISACORE_BIN" -emit obj -O0 -o "$WORK/frontend_lexer.o" "$FIXTURE"

cat > "$WORK/harness.c" <<'EOF'
#include "frontend_lexer.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static uint8_t *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = malloc((size_t)n + 1);
    if (fread(b, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(b); return NULL; }
    fclose(f); b[n] = 0; return b;
}
int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <file>\n", argv[0]); return 2; }
    uint8_t *src = slurp(argv[1]); if (!src) { fprintf(stderr, "read failed\n"); return 3; }
    printf("%llu\n", (unsigned long long)frontend_lexer_token_checksum(src));
    free(src); return 0;
}
EOF

CFLAGS=(-O0 -I "$WORK" "$WORK/harness.c" "$SHIMS" "$WORK/frontend_lexer.o" -o "$WORK/harness")
[[ "$(uname -s)" == "Darwin" ]] && CFLAGS=(-Wl,-undefined,dynamic_lookup "${CFLAGS[@]}")
clang "${CFLAGS[@]}"

# Corpus: caller-supplied files, else a built-in standalone set.
corpus=("$@")
if [[ ${#corpus[@]} -eq 0 ]]; then
	mk() { printf '%b' "$2" > "$WORK/$1"; corpus+=("$WORK/$1"); }
	mk simple.elisa       'hello\n'
	mk ops.elisa          'def foo:\n    x <- 1\n    y <- 2\nz <- 3\n'
	mk aligned.elisa      'def f(aligned: i64) -> i64:\n    return aligned\n'
	mk numbers.elisa      'x <- 0xff\ny <- 1.5\nz <- 1e3\n'
	mk strings.elisa      'msg <- "hello world"\n'
	mk ranges.elisa       'for i in 1 ..= 4:\n    pass\n'
	# Keyword coverage incl. 8-char keywords (continue/offsetof) that the old
	# hand-rolled fast-path mis-filtered, and `aligned` which must stay an ident.
	mk keywords.elisa     'def f:\n    if true:\n        continue\n    x <- offsetof\n    aligned <- 1\n    return x\n'
fi

fail=0
for file in "${corpus[@]}"; do
	stage1="$("$WORK/harness" "$file")"
	stage0="$("$ELISACORE_BIN" -emit tokens "$file" | sed -n 's/.*"checksum": *\([0-9]*\).*/\1/p')"
	if [[ "$stage1" == "$stage0" && -n "$stage0" ]]; then
		printf 'OK    %-20s %s\n' "$(basename "$file")" "$stage0"
	else
		printf 'DRIFT %-20s stage1=%s stage0=%s\n' "$(basename "$file")" "$stage1" "$stage0"
		fail=1
	fi
done

[[ $fail -eq 0 ]] && echo "lexer parity: stage1 == stage0" || { echo "LEXER PARITY FAILED" >&2; exit 1; }
