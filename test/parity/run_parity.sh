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

for tool in "$ELISACORE_BIN" clang od wc; do
	command -v "$tool" >/dev/null 2>&1 || [[ -x "$tool" ]] || { echo "error: missing $tool" >&2; exit 2; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

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
        checksum: u64 = frontend_lexer_token_checksum_with_len(&bytes[0], $source_len)
        print(checksum)
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
	stage0="$("$ELISACORE_BIN" -emit tokens "$file" | sed -n 's/.*"checksum": *\([0-9]*\).*/\1/p')"
	if [[ "$stage1" == "$stage0" && -n "$stage0" ]]; then
		printf 'OK    %-20s %s\n' "$(basename "$file")" "$stage0"
	else
		printf 'DRIFT %-20s stage1=%s stage0=%s\n' "$(basename "$file")" "$stage1" "$stage0"
		fail=1
	fi
	case_index=$((case_index + 1))
done

[[ $fail -eq 0 ]] && echo "lexer parity: stage1 == stage0" || { echo "LEXER PARITY FAILED" >&2; exit 1; }
