#!/usr/bin/env bash
# Behavioral smoke for field-assignment type checking — the engine's batch-5 unlock (the
# first NEW check the field-type registry enables). `p.x <- v` where v cannot inhabit
# field x's declared type is flagged (TypeMismatch), the same oracle the local `x <- v`
# check uses. Compatible / unknown-typed assignments are silent; 0 FP across the corpus.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "field-assign smoke FAIL: $1" >&2; exit 1; }

# 1. a string assigned to an i64 field MUST be flagged.
out=$(printf 'struct C:\n    count: i64\n\ndef f(c: mutable C) -> void:\n    c.count <- "s"\n' | "$RPT")
echo "$out" | grep -q "\"count\" expects i64, got static u8" || fail "string-to-i64-field not flagged: $out"

# 2. a bool assigned to a string field MUST be flagged.
out=$(printf 'struct C:\n    name: sview\n\ndef f(c: mutable C) -> void:\n    c.name <- true\n' | "$RPT")
echo "$out" | grep -q "\"name\" expects sview, got bool" || fail "bool-to-string-field not flagged: $out"

# 3. a compatible int assigned to an i64 field must NOT be flagged.
out=$(printf 'struct C:\n    count: i64\n\ndef f(c: mutable C) -> void:\n    c.count <- 5\n' | "$RPT")
echo "$out" | grep -q "expects" && fail "false positive on int-to-i64-field: $out"

# 4. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "expects .*, got" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t type-mismatch false positives across frontend+stdlib"

echo "field-assign smoke OK: p.x <- v checked against field x's type, silent on compatible, 0 FP across frontend+stdlib"
