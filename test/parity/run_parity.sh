#!/usr/bin/env bash
# Cross-repo lexer parity: stage1 (this repo's Elisa lexer) vs stage0 (Elisa-core).
#
# For each corpus file we compute token-kind and full-token checksums and require they match:
#   * stage1: the self-hosted Elisa lexer, compiled once into a native checksum
#     harness.
#   * stage0: a tiny Go oracle that imports Elisa-core's lexer package.
#
# Inputs must be STANDALONE .elisa files (no `include` directives): the Elisa
# harness lexes raw file bytes, while `-emit tokens` lexes include-expanded
# source — they coincide only when there are no includes.
#
# Resolve Elisa-core via $ELISA_CORE (default: conventional sibling path).
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

# Always run against a freshly built compiler (sets ELISACORE_BIN).
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

FIXTURE="$REPO_ROOT/test/fixtures/lexer/frontend_lexer.elisa"

for tool in clang go; do
	command -v "$tool" >/dev/null 2>&1 || { echo "error: missing $tool" >&2; exit 2; }
done

WORK="$(mktemp -d)"
if [[ "${PARITY_KEEP_WORK:-0}" == "1" ]]; then
	echo "parity workdir: $WORK" >&2
	trap 'echo "parity workdir kept: '"$WORK"'" >&2' EXIT INT TERM HUP
else
	trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fi

cat > "$WORK/stage0_full_tokens.go" <<'EOF'
package main

import (
	"fmt"
	"os"

	"elisacore/src/lexer"
)

const offset uint64 = 1469598103934665603
const prime uint64 = 1099511628211

func mix(hash uint64, value uint64) uint64 {
	return (hash ^ value) * prime
}

func hashString(hash uint64, value string) uint64 {
	hash = mix(hash, uint64(len(value)))
	for i := 0; i < len(value); i++ {
		hash = mix(hash, uint64(value[i]))
	}
	return hash
}

func kindCode(kind lexer.TokenKind) uint64 {
	switch kind {
	case lexer.TOKEN_RANGE_LE:
		return 109
	default:
		return uint64(kind) + 1
	}
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: stage0_full_tokens <file>")
		os.Exit(2)
	}
	source, err := os.ReadFile(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(3)
	}
	l := lexer.New(os.Args[1], source)
	kindHash := offset
	fullHash := offset
	for {
		token := l.NextToken()
		code := kindCode(token.Kind)
		kindHash = mix(kindHash, code)
		fullHash = mix(fullHash, code)
		fullHash = mix(fullHash, uint64(token.Pos.Line))
		fullHash = mix(fullHash, uint64(token.Pos.Col))
		fullHash = hashString(fullHash, token.Text)
		fullHash = hashString(fullHash, token.Suffix)
		if token.Kind == lexer.TOKEN_EOF {
			break
		}
	}
	fmt.Printf("%d %d\n", kindHash, fullHash)
}
EOF
(cd "$ELISA_CORE/compiler" && go build -o "$WORK/stage0_full_tokens" "$WORK/stage0_full_tokens.go")

cat > "$WORK/stage1_lexer_harness.elisa" <<EOF
include "$FIXTURE"

def stage1_lexer_checksums(source: u8&, source_len: usize, kind_out: mutable u64&, full_out: mutable u64&):
    checksums: FrontendLexerChecksums = frontend_lexer_stream_checksums_with_len(source, source_len) can Memory.Allocate, Abort.Panic
    kind_out[0] <- checksums.kind
    full_out[0] <- checksums.full


export func stage1_lexer_checksums_export(source: u8&, source_len: usize, kind_out: mutable u64&, full_out: mutable u64&) -> void = stage1_lexer_checksums
EOF

"$ELISACORE_BIN" -emit header -o "$WORK/stage1_lexer_harness.h" "$WORK/stage1_lexer_harness.elisa" >/dev/null
"$ELISACORE_BIN" -emit obj -O2 -o "$WORK/stage1_lexer_harness.o" "$WORK/stage1_lexer_harness.elisa" >/dev/null

cat > "$WORK/stage1_lexer_harness.c" <<'EOF'
#include "stage1_lexer_harness.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint8_t *slurp(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long n = ftell(f);
    if (n < 0) { fclose(f); return NULL; }
    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); return NULL; }
    uint8_t *buf = (uint8_t *)malloc((size_t)n + 1);
    if (!buf) { fclose(f); return NULL; }
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(buf);
        return NULL;
    }
    fclose(f);
    buf[n] = 0;
    *out_len = (size_t)n;
    return buf;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <file>\n", argv[0]);
        return 2;
    }
    size_t source_len = 0;
    uint8_t *source = slurp(argv[1], &source_len);
    if (!source) {
        fprintf(stderr, "read failed: %s\n", argv[1]);
        return 3;
    }
    uint64_t kind = 0;
    uint64_t full = 0;
    stage1_lexer_checksums_export(source, source_len, &kind, &full);
    printf("%llu %llu\n", (unsigned long long)kind, (unsigned long long)full);
    free(source);
    return 0;
}
EOF

stage1_link_flags=(-O2 -I "$WORK" "$WORK/stage1_lexer_harness.c" "$WORK/stage1_lexer_harness.o" -o "$WORK/stage1_lexer_harness")
[[ "$(uname -s)" == "Darwin" ]] && stage1_link_flags=(-Wl,-undefined,dynamic_lookup "${stage1_link_flags[@]}")
clang "${stage1_link_flags[@]}"

stage1_checksum() {
	local file="$1"
	"$WORK/stage1_lexer_harness" "$file"
}

# Corpus: caller-supplied files, else a built-in standalone set.
corpus=("$@")
if [[ ${#corpus[@]} -eq 0 ]]; then
	mk() { printf '%b' "$2" > "$WORK/$1"; corpus+=("$WORK/$1"); }
	mk simple.elisa       'hello\n'
	mk ops.elisa          'def foo:\n    x <- 1\n    y <- 2\nz <- 3\n'
	mk aligned.elisa      'def f(aligned: i64) -> i64:\n    return aligned\n'
	mk numbers.elisa      'x <- 0xff\ny <- 1.5\nz <- 1e3\n'
	mk strings.elisa      'msg <- "hello world"\n'
	mk escaped_literals.elisa 'msg <- "a\\n\\x41"\nch <- '"'"'\\n'"'"'\n'
	mk ranges.elisa       'for i in 1 ..= 4:\n    pass\n'
	mk appended_ops.elisa 'x |> f; y => { z }\n'
	mk float_edges.elisa  'a <- .5\nb <- 1.\nc <- 1.f32\nd <- 1.e3\n'
	mk block_comment.elisa 'def f:\n    """doc\nspanning"""\n    g()\n'
	mk line_directive.elisa '#line 12 included.elisa\nvalue <- 1\n'
	mk aliases.elisa      'size_of(Header) align_of(Header) offset_of(Header, count) value is Pattern\n'
	# Keyword coverage incl. 8-char keywords (continue/offsetof) that the old
	# hand-rolled fast-path mis-filtered, and `aligned` which must stay an ident.
	mk keywords.elisa     'def f:\n    if true:\n        continue\n    x <- offsetof\n    aligned <- 1\n    return x\n'
fi

fail=0
for file in "${corpus[@]}"; do
	stage1="$(stage1_checksum "$file")"
	stage0="$("$WORK/stage0_full_tokens" "$file")"
	if [[ "$stage1" == "$stage0" && -n "$stage0" ]]; then
		printf 'OK    %-20s %s\n' "$(basename "$file")" "$stage0"
	else
		printf 'DRIFT %-20s stage1=%s stage0=%s\n' "$(basename "$file")" "$stage1" "$stage0"
		fail=1
	fi
done

[[ $fail -eq 0 ]] && echo "lexer parity: stage1 == stage0" || { echo "LEXER PARITY FAILED" >&2; exit 1; }
