#!/usr/bin/env bash
# Behavioral smoke for reserved keywords used as names (parity with stage0's
# parser_reserved_word_names.go). A name-like keyword (`to`, `stack`, `heap`, `tail`,
# `error`, `packed`) in a declaration, assignment, parameter, field, loop binder or use
# gets stage0's sentence at the word's own span, once per occurrence, with no cascade; the
# whole frontend + stdlib must stay free of it.
#
# Usage: test/parity/reserved_word_names_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "reserved-word smoke FAIL: $1" >&2; exit 1; }
sentence() { echo "\`$1\` is a reserved keyword and cannot be used as a name"; }
# expect SOURCE WORD COUNT: exactly COUNT reports naming WORD, and nothing else.
expect() {
  local out reports others
  out=$(printf "$1" | "$RPT")
  # parse_report lists each parse error twice: in its `P` section (`  COL LLINE ...`) and
  # again under `D`. Count the `P` rows.
  reports=$(grep -E '^ +[0-9]+ L[0-9]+ ' <<< "$out" | grep -c -F "$(sentence "$2")" || true)
  [ "$reports" -eq "$3" ] || fail "expected $3 report(s) for \`$2\`, got $reports: $out"
  others=$(grep -E "unexpected token|expected IDENT|may fall through" <<< "$out" || true)
  [ -z "$others" ] || fail "cascade after \`$2\`: $others"
}

# Declarations, assignments and uses, one report per occurrence.
for word in to stack heap tail error packed; do
  expect "def f(value: i64) -> i64:\n    ${word}: i64 = value + 1\n    ${word} * 2\n" "$word" 2
done
expect "def g() -> i64:\n    packed = 3\n    packed\n" packed 2
expect "def h(value: mutable i64) -> i64:\n    value <- 1\n    error <- 4\n    value\n" error 1
# Parameters, fields and struct-literal labels go through the name expectation.
expect "def p(stack: i64) -> i64:\n    stack + 1\n" stack 2
expect "struct Node:\n    tail: i64\n\ndef n() -> Node:\n    Node{tail: 1}\n" tail 2
# Loop binders.
expect "def l() -> i64:\n    total: mutable i64 = 0\n    for to in 0..<3:\n        total <- total + to\n    total\n" to 2
expect "def m() -> i64:\n    total: mutable i64 = 0\n    for heap, x in [1, 2]:\n        total <- total + x\n    total\n" heap 1

# The whole frontend + stdlib compiles on stage0, so any report there is a false positive.
n=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "is a reserved keyword and cannot be used as a name" || true)
  n=$((n + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$n" -eq 0 ] || fail "$n reserved-word false positives across frontend+stdlib"

echo "reserved-word smoke OK: declarations, assignments, uses, parameters, fields and loop binders reported once each, 0 false positives across frontend+stdlib"
