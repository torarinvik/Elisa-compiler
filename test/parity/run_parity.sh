#!/usr/bin/env bash
# Cross-repo lexer parity: stage1 (this repo's Elisa lexer) vs stage0 (Elisa-core).
#
# For each corpus file we compute two token-kind checksums and require they match:
#   * stage1: the self-hosted Elisa lexer, compiled into a tiny Elisa checksum
#     harness generated per corpus file.
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

FIXTURE="$REPO_ROOT/test/fixtures/lexer/frontend_lexer.elisa"

for tool in "$ELISACORE_BIN" clang go od wc; do
	command -v "$tool" >/dev/null 2>&1 || [[ -x "$tool" ]] || { echo "error: missing $tool" >&2; exit 2; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

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
	tokens := lexer.New(os.Args[1], source).Tokenize()
	kindHash := mix(offset, uint64(len(tokens)))
	fullHash := mix(offset, uint64(len(tokens)))
	for _, token := range tokens {
		code := kindCode(token.Kind)
		kindHash = mix(kindHash, code)
		fullHash = mix(fullHash, code)
		fullHash = mix(fullHash, uint64(token.Pos.Line))
		fullHash = mix(fullHash, uint64(token.Pos.Col))
		fullHash = hashString(fullHash, token.Text)
		fullHash = hashString(fullHash, token.Suffix)
	}
	fmt.Printf("%d %d\n", kindHash, fullHash)
}
EOF
(cd "$ELISA_CORE/compiler" && go build -o "$WORK/stage0_full_tokens" "$WORK/stage0_full_tokens.go")

stage1_checksum() {
	local file="$1"
	local name="$2"
	local source_len
	local bytes
	local array_len
	local harness
	local obj
	local exe

	source_len="$(wc -c < "$file" | tr -d '[:space:]')"
	bytes="$(od -An -v -tu1 "$file" | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//; s/ /, /g')"
	if [[ -z "$bytes" ]]; then
		bytes="0"
		array_len=1
	else
		array_len="$source_len"
	fi

	harness="$WORK/stage1_${name}.elisa"
	obj="$WORK/stage1_${name}.o"
	exe="$WORK/stage1_${name}"
	cat > "$harness" <<EOF
include "$FIXTURE"

def main() -> int:
    can Console.Write, Memory.Allocate, Console.Format, Abort.Panic:
        bytes: u8[$array_len] = [$bytes]
        kind_checksum: u64 = frontend_lexer_token_checksum_with_len(&bytes[0], $source_len)
        full_checksum: u64 = frontend_lexer_token_full_checksum_with_len(&bytes[0], $source_len)
        printr(kind_checksum)
        printr(" ")
        print(full_checksum)
        return 0
EOF

	"$ELISACORE_BIN" -emit obj -O0 -o "$obj" "$harness" >/dev/null
	local link_flags=(-O0 "$obj" -o "$exe")
	[[ "$(uname -s)" == "Darwin" ]] && link_flags=(-Wl,-undefined,dynamic_lookup "${link_flags[@]}")
	clang "${link_flags[@]}"
	"$exe"
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
case_index=0
for file in "${corpus[@]}"; do
	stage1="$(stage1_checksum "$file" "$case_index")"
	stage0="$("$WORK/stage0_full_tokens" "$file")"
	if [[ "$stage1" == "$stage0" && -n "$stage0" ]]; then
		printf 'OK    %-20s %s\n' "$(basename "$file")" "$stage0"
	else
		printf 'DRIFT %-20s stage1=%s stage0=%s\n' "$(basename "$file")" "$stage1" "$stage0"
		fail=1
	fi
	case_index=$((case_index + 1))
done

[[ $fail -eq 0 ]] && echo "lexer parity: stage1 == stage0" || { echo "LEXER PARITY FAILED" >&2; exit 1; }
