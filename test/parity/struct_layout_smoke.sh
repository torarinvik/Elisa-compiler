#!/usr/bin/env bash
# Behavioral smoke for struct declaration layout checks — unknown field types and
# direct self-recursion (parity with stage0 ports). A field whose type is an unresolved
# bare name flags UnknownFieldType; a struct field typing itself directly (infinite size)
# flags RecursiveStruct. Refs/optionals/generics are never flagged (sound subset).
# 0 FP across the frontend + stdlib.
#
# Usage: test/parity/struct_layout_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "struct-layout smoke FAIL: $1" >&2; exit 1; }

# 1. An unknown field type MUST be flagged (only lowercase names, to avoid cross-module false positives).
out=$(printf 'struct Point:\n    x: unknown\n    y: i64\n' | "$RPT")
echo "$out" | grep -q "L2 .*has unknown type 'unknown'" || fail "unknown field type not flagged on field line: $out"

# 2. A directly self-recursive struct MUST be flagged.
out=$(printf 'struct Node:\n    val: i64\n    next: Node\n' | "$RPT")
echo "$out" | grep -q "L3 .*directly self-recursive" || fail "direct self-recursion not flagged on field line: $out"

# 3. A ref-indirected self-reference must NOT be flagged (sound indirection).
out=$(printf 'struct Node:\n    val: i64\n    next: Node&\n' | "$RPT")
echo "$out" | grep -q "directly self-recursive" && fail "false positive on ref-indirected self-ref: $out"

# 4. An optional self-reference must NOT be flagged (sound indirection).
out=$(printf 'struct Node:\n    val: i64\n    next: Node?\n' | "$RPT")
echo "$out" | grep -q "directly self-recursive" && fail "false positive on optional self-ref: $out"

# 5. Distinct field types must NOT be flagged.
out=$(printf 'struct Point:\n    x: i64\n    y: i64\n' | "$RPT")
echo "$out" | grep -q "unknown type" && fail "false positive on i64 field: $out"
echo "$out" | grep -q "directly self-recursive" && fail "false positive on distinct fields: $out"

# 6. Mutual recursion via refs is sound and NOT flagged.
out=$(printf 'struct A:\n    b: B&\nstruct B:\n    a: A&\n' | "$RPT")
echo "$out" | grep -q "directly self-recursive" && fail "false positive on mutual ref-recursion: $out"

# 7. 0 FP across frontend + stdlib.
n=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "unknown type|directly self-recursive" || true)
  n=$((n + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$n" -eq 0 ] || fail "$n struct-layout false positives across frontend+stdlib"

echo "struct-layout smoke OK: flags unknown field types + direct self-recursion, silent on refs/optionals/mutuals, 0 false positives across frontend+stdlib"
