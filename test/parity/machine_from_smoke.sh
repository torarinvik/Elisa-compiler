#!/usr/bin/env bash
# docs/125 §5 — `machine from START [decreases M]:` state-machine expressions parse (P 0)
# and desugar to a resolvable value-block (D 0): the acyclic scanner shape yielding a
# TokenKind, and the cyclic form with a threaded mutable local + `decreases`. States are
# the variants of an existing enum; `next`/`done` are contextual arm terminators.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "machine from smoke FAIL: $1" >&2; exit 1; }

# 1. Acyclic machine yielding a value (inferred result type from the binding).
out=$(printf 'const enum TK of u8:\n    IntLit\n    FloatLit\nconst enum Num of u8:\n    Integer\n    Fraction\ndef scan(f: bool) -> TK:\n    k: TK = machine from Num.Integer:\n        Num.Integer:\n            next Num.Fraction if f\n            done TK.IntLit\n        Num.Fraction:\n            done TK.FloatLit\n    return k\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "acyclic machine had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "acyclic machine had diagnostics: $out"

# 2. Cyclic machine with `decreases` + a threaded mutable local.
out=$(printf 'const enum St of u8:\n    Step\n    Stop\ndef down(x: i64) -> i64:\n    n: mutable i64 = x\n    total: i64 = machine from St.Step decreases n:\n        St.Step:\n            n <- n - 1\n            next St.Stop if n <= 0\n            next St.Step\n        St.Stop:\n            done n\n    return total\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "cyclic machine had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "cyclic machine had diagnostics: $out"

echo "machine from smoke OK: acyclic + cyclic(decreases, threaded mutable) state machines parse P0 D0"
