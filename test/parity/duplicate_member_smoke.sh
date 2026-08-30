#!/usr/bin/env bash
# Behavioral smoke for the stage1 DuplicateField / DuplicateVariant diagnostics (parity with
# stage0's `duplicate field "x" in struct "P"` / `duplicate variant "A" in enum "E"` errors).
# Builds the breadth `parse_report` reporter and asserts the checks FIRE on a repeated field /
# variant and STAY SILENT on distinct members and across the whole frontend + stdlib.
#
# Usage: test/parity/duplicate_member_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"   # sets ELISACORE_BIN to a fresh build
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "duplicate-member smoke FAIL: $1" >&2; exit 1; }

# 1. a repeated struct field MUST be flagged.
out=$(printf 'struct P:\n    x: i64\n    x: i64\n' | "$RPT")
echo "$out" | grep -q "duplicate field \"x\" in struct \"P\"" || fail "duplicate field not flagged: $out"

# 2. a repeated enum variant MUST be flagged.
out=$(printf 'enum E:\n    A\n    A\n' | "$RPT")
echo "$out" | grep -q "duplicate variant \"A\" in enum \"E\"" || fail "duplicate variant not flagged: $out"

# 3. distinct fields/variants must NOT be flagged.
out=$(printf 'struct Q:\n    a: i64\n    b: i64\n\nenum F:\n    X\n    Y(v: i64)\n' | "$RPT")
echo "$out" | grep -q "duplicate field" && fail "false positive on distinct fields: $out"
echo "$out" | grep -q "duplicate variant" && fail "false positive on distinct variants: $out"

# 4. the whole frontend + stdlib must produce ZERO duplicate-member findings.
n=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "duplicate field|duplicate variant" || true)
  n=$((n + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$n" -eq 0 ] || fail "$n duplicate-member false positives across frontend+stdlib"

echo "duplicate-member smoke OK: flags repeated struct field + enum variant, silent on distinct members, 0 false positives across frontend+stdlib"
