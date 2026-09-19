#!/usr/bin/env bash
# Behavioral smoke for struct declaration layout checks — unknown field types and
# direct self-recursion (parity with stage0 ports). A field whose type is an unresolved
# bare name flags UnknownFieldType; a struct field typing itself directly (infinite size)
# flags RecursiveStruct. Refs/optionals/generics are never flagged (sound subset).
# Check the complete compiler/include closure for false positives.
#
# Usage: test/parity/struct_layout_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "struct-layout smoke FAIL: $1" >&2; exit 1; }

# 1. An unknown field type MUST be flagged regardless of capitalization.
out=$(printf 'struct Point:\n    x: unknown\n    y: i64\n' | "$RPT")
grep -q "L2 .*unknown type \"unknown\"" <<< "$out" || fail "unknown field type not flagged on field line: $out"
out=$(printf 'struct Point:\n    x: Missing\n    y: i64\n' | "$RPT")
grep -q 'L2 .*unknown type "Missing"' <<< "$out" || fail "capitalized unknown field type not flagged: $out"

# 2. A directly self-recursive struct MUST be flagged.
out=$(printf 'struct Node:\n    val: i64\n    next: Node\n' | "$RPT")
grep -q "L3 .*directly self-recursive" <<< "$out" || fail "direct self-recursion not flagged on field line: $out"

# 3. A ref-indirected self-reference must NOT be flagged (sound indirection).
out=$(printf 'struct Node:\n    val: i64\n    next: Node&\n' | "$RPT")
grep -q "directly self-recursive" <<< "$out" && fail "false positive on ref-indirected self-ref: $out"

# 4. An optional self-reference must NOT be flagged (sound indirection).
out=$(printf 'struct Node:\n    val: i64\n    next: Node?\n' | "$RPT")
grep -q "directly self-recursive" <<< "$out" && fail "false positive on optional self-ref: $out"

# 5. Distinct field types must NOT be flagged.
out=$(printf 'struct Point:\n    x: i64\n    y: i64\n' | "$RPT")
grep -q "unknown type" <<< "$out" && fail "false positive on i64 field: $out"
grep -q "directly self-recursive" <<< "$out" && fail "false positive on distinct fields: $out"

# 6. Mutual recursion via refs is sound and NOT flagged.
out=$(printf 'struct A:\n    b: B&\nstruct B:\n    a: A&\n' | "$RPT")
grep -q "directly self-recursive" <<< "$out" && fail "false positive on mutual ref-recursion: $out"

# 7. A qualified type in a known module must flag an unknown member type.
out=$(printf 'module M:\n    struct Good:\n        x: i64\n\nstruct Bad:\n    x: M::Missing\n' | "$RPT")
grep -q "unknown type \"M::Missing\"" <<< "$out" || fail "qualified unknown field type not flagged: $out"

# 8. Nested/compound qualified paths remain conservative until nested ownership
# metadata is modeled; a known nested type must not produce a false positive.
out=$(printf 'module M::N:\n    struct Good:\n        x: i64\n\nstruct Uses:\n    x: M::N::Good\n' | "$RPT")
grep -q "unknown type" <<< "$out" && fail "false positive on nested qualified type: $out"

# 9. Check a COMPLETE compilation unit. Feeding each included file separately to the
# reporter omits its imported types and mistakes real missing declarations for false
# positives. The native driver's interface mode expands includes and runs semantic
# validation over the actual compiler and stdlib without generating native code.
layout_log="$REPO_ROOT/build/struct_layout_self.log"
if ! bash "$REPO_ROOT/scripts/elisac_stage1.sh" -permissive -emit iface \
    -o "$REPO_ROOT/build/struct_layout_self.elisai" "$REPO_ROOT/src/driver/elisac.elisa" \
    >"$layout_log" 2>&1; then
  tail -20 "$layout_log" >&2
  fail "whole compiler/include closure rejected (see $layout_log)"
fi

echo "struct-layout smoke OK: unknown types and recursion checked; whole compiler/include closure accepted"
