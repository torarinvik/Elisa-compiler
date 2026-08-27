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

# 3. docs/125 §5 state payloads — `next` constructs the successor's payload, the arm
# header binds it, so a body reading the binding resolves (the `is`-dispatch desugar binds
# each state's fields). Regular (non-const) enum so variants can carry fields. Also covers
# an entry-state payload `machine from Phase.Mid(true)` is exercised via the routed form.
out=$(printf 'enum Phase:\n    Start\n    Mid(bool)\n    End(i64)\ndef run(x: i64) -> i64:\n    r: i64 = machine from Phase.Start:\n        Phase.Start:\n            next Phase.Mid(true) if x > 0\n            next Phase.Mid(false)\n        Phase.Mid(flag):\n            next Phase.End(10) if flag\n            next Phase.End(20)\n        Phase.End(val):\n            done val\n    return r\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "payload machine had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "payload machine had diagnostics (binding unresolved?): $out"

# 4. Entry-state payload: `machine from Once.Only(seed)` binds `val` in the sole arm.
out=$(printf 'enum Once:\n    Only(i64)\ndef echo(seed: i64) -> i64:\n    r: i64 = machine from Once.Only(seed):\n        Once.Only(val):\n            done val\n    return r\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "entry-payload machine had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "entry-payload machine had diagnostics: $out"

# 5. R5 declared out-edges `State -> {A, B}:` parse and desugar cleanly (stage0 owns the R5
# enforcement; stage1 consumes the clause structurally).
out=$(printf 'enum Route:\n    In(i64)\n    Left\n    Right\ndef route(x: i64) -> i64:\n    r: i64 = machine from Route.In(x):\n        Route.In(v) -> {Left, Right}:\n            next Route.Left if v > 0\n            next Route.Right\n        Route.Left:\n            done 1\n        Route.Right:\n            done 2\n    return r\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "declared-out machine had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "declared-out machine had diagnostics: $out"

# 6. Canonical graph syntax plus function-local typed states. `-> Mid(bool)` is an enum
# constructor checked by the ordinary type system; `=> value` is the expression result.
out=$(printf 'def classify(x: i64) -> i64:\n    state Start\n    state Mid(flag: bool)\n    state End(value: i64)\n    return start Start:\n        Start:\n            -> Mid(true) if x > 0\n            -> Mid(false)\n        Mid(flag):\n            -> End(10) if flag\n            -> End(20)\n        End(value):\n            => value\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "local typed arrow machine had parse errors: $out"
echo "$out" | grep -q "^D 0$" || fail "local typed arrow machine had diagnostics: $out"

# 7. The transition payload is not documentation: ordinary enum-constructor checking
# rejects an i64 sent to a bool state parameter.
out=$(printf 'def bad() -> i64:\n    state Start\n    state Mid(flag: bool)\n    return start Start:\n        Start:\n            -> Mid(1)\n        Mid(flag):\n            => 0\n' | "$RPT")
echo "$out" | grep -q "^P 0$" || fail "bad typed transition should remain structurally parseable: $out"
if echo "$out" | grep -q "^D 0$"; then
  fail "wrong transition payload type was accepted: $out"
fi

echo "machine from smoke OK: legacy aliases + canonical arrows + local typed states + payloads + graph checks parse P0 D0"
