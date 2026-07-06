#!/usr/bin/env bash
# Behavioral smoke for the lmut (linear-mutable) aliasing check: an argument bound to an
# `lmut` parameter may not name the same place as another argument of the same call (the
# single-live-binding rule). Asserts the check FIRES on a real violation, stays silent on
# distinct args / disjoint fields, and produces zero false positives across the whole
# frontend + stdlib — which itself passes ~114 `lmut Lexer`/`lmut Parser` receivers.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "lmut-alias smoke FAIL: $1" >&2; exit 1; }
MSG="aliases another argument of the same call"

PRELUDE='struct Counter:\n    value: mutable i64\n\ndef combine(a: lmut Counter, b: lmut Counter) -> void:\n    a.value <- a.value + b.value\n\n'

# 1. POSITIVE: the same variable passed to two lmut params must be flagged.
out=$(printf "${PRELUDE}def use() -> void:\n    c: mutable Counter = Counter{value: 1}\n    combine(c, c)\n" | "$RPT")
echo "$out" | grep -q "$MSG" || fail "combine(c, c) not flagged: $out"

# 2. Distinct variables must stay silent.
out=$(printf "${PRELUDE}def use() -> void:\n    c: mutable Counter = Counter{value: 1}\n    d: mutable Counter = Counter{value: 2}\n    combine(c, d)\n" | "$RPT")
echo "$out" | grep -q "$MSG" && fail "false positive on combine(c, d): $out"

# 3. Disjoint fields of one root do NOT alias — must stay silent.
out=$(printf 'struct Counter:\n    value: mutable i64\nstruct Pair:\n    a: mutable Counter\n    b: mutable Counter\ndef combine(x: lmut Counter, y: lmut Counter) -> void:\n    x.value <- x.value + y.value\ndef use() -> void:\n    p: mutable Pair = Pair{a: Counter{value: 1}, b: Counter{value: 2}}\n    combine(p.a, p.b)\n' | "$RPT")
echo "$out" | grep -q "$MSG" && fail "false positive on disjoint fields combine(p.a, p.b): $out"

# 4. Zero false positives across the whole frontend + stdlib (heavy real lmut usage).
t=0
while IFS= read -r f; do
    c=$("$RPT" < "$f" 2>/dev/null | grep -cE "$MSG" || true)
    t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t lmut-alias false positives across frontend+stdlib"

echo "lmut-alias smoke OK: flags aliased lmut args, silent on distinct/disjoint, 0 FP across frontend+stdlib"
