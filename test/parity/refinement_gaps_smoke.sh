#!/usr/bin/env bash
# Refinement checks stage1 used to skip, each one stage0 reports:
#   1. a predicate with no law in scope (`i64 is InRange[0, 255]` with no `law InRange`);
#   2. an out-of-range literal returned through a plain alias (`-> ExitStatus`), bare or
#      module-qualified;
#   3. an unguarded signed parameter returned into a `[0, ...]` refinement under SMT.
# A guarded narrowing must still compile cleanly.
#
# Usage: test/parity/refinement_gaps_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
work="$(mktemp -d "${TMPDIR:-/tmp}/refinement-gaps.XXXXXX")"
trap 'rm -rf "$work"' EXIT
fail() { echo "refinement gaps smoke FAIL: $1" >&2; exit 1; }
LAW='law InRange(self: i64, low: i64, high: i64) = self >= low and self <= high'

# expect NAME PATTERN [ENV...] : the source in $work/NAME.elisa must report PATTERN.
expect() {
  local name="$1" pattern="$2"; shift 2
  env ELISA_STAGE1_SEMANTIC_GATE=1 "$@" "$ELISAC" -emit obj -o "$work/$name.o" "$work/$name.elisa" > "$work/$name.log" 2>&1 || true
  grep -q "$pattern" "$work/$name.log" || fail "$name: expected '$pattern', got: $(head -3 "$work/$name.log")"
}

printf 'type Status = i64 is InRange[0, 255]\n\ndef ok() -> Status:\n    return 0\n' > "$work/no_law.elisa"
expect no_law 'refinement predicate "InRange" is not a law'

printf '%s\ntype Status = i64 is InRange[0, 255]\n\ndef bad(n: usize) -> Status:\n    if n == 9:\n        return 300\n    return 0\n' "$LAW" > "$work/alias_literal.elisa"
expect alias_literal 'refinement "InRange" is violated'

printf '%s\nmodule Cli:\n    public:\n        type Status = i64 is InRange[0, 255]\n\ndef bad(n: usize) -> Cli::Status:\n    if n == 9:\n        return 300\n    return 0\n' "$LAW" > "$work/qualified_literal.elisa"
expect qualified_literal 'refinement "InRange" is violated'

printf '%s\ntype Status = i64 is InRange[0, 255]\n\ndef narrow(v: i64) -> Status:\n    return v\n' "$LAW" > "$work/smt_signed.elisa"
expect smt_signed 'could not be proven statically' ELISA_STAGE1_SMT=1

printf '%s\ntype Status = i64 is InRange[0, 255]\n\ndef checked(v: i64) -> Status:\n    if v >= 0 and v <= 255:\n        return v\n    return 0\n' "$LAW" > "$work/guarded.elisa"
ELISA_STAGE1_SEMANTIC_GATE=1 "$ELISAC" -emit obj -o "$work/guarded.o" "$work/guarded.elisa" > "$work/guarded.log" 2>&1 || fail "guarded narrowing rejected: $(head -3 "$work/guarded.log")"
echo "refinement gaps smoke OK: missing law, alias literal (bare and qualified), SMT signed return, guarded accept"
