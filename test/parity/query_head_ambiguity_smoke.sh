#!/usr/bin/env bash
# Which QUERY keyword a `count`/`sum`/`any`/`all` expression is, when two of them share a line.
#
# `Expr.Comprehension` drops the head keyword, so the backend recovers it from a parser side
# table. Keyed by LINE alone, the lookup returned the FIRST row for the line and two queries on
# one line both read the first one's keyword — `(count x …) * 10 + (sum y …)` answered 33 where
# stage0 answers 42, silently. Rows are now keyed by (line, BINDER).
#
# That leaves one shape genuinely undecidable: same line, SAME binder, different keyword. The
# node keeps only the line, so nothing separates them. The contract is that stage1 DECLINES
# there rather than guessing — a decline is loud at link time, a wrong quantifier is silent
# forever (guessing is exactly how `all x in [1, 0] where x > 0` once returned TRUE).
#
# Not in the adversarial suite: that ratchets DECLINE at zero, and this decline is deliberate.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
RT="$ROOT/build/runtime/elisacore_runtime.o"
[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ] || { echo "query_head_ambiguity SKIP: no stage1 binary"; exit 0; }
[ -f "$RT" ] || { echo "query_head_ambiguity SKIP: no runtime object"; exit 0; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT INT TERM HUP
pass=0; total=0

# $1 name, $2 source, $3 expected exit code, or "decline" for "must not compile"
case_is() {
    local name="$1" src="$2" want="$3"
    total=$((total + 1))
    printf '%b' "$src" > "$WORK/$name.elisa"
    if ! "$STAGE1" -emit exe -o "$WORK/$name" "$WORK/$name.elisa" >/dev/null 2>&1; then
        if [ "$want" = "decline" ]; then pass=$((pass + 1)); else echo "  FAIL $name: declined, expected $want"; fi
        return
    fi
    if [ "$want" = "decline" ]; then
        "$WORK/$name" >/dev/null 2>&1
        echo "  FAIL $name: COMPILED and answered $? — an ambiguous head must decline, not guess"
        return
    fi
    "$WORK/$name" >/dev/null 2>&1
    local got=$?
    if [ "$got" -eq "$want" ]; then pass=$((pass + 1)); else echo "  FAIL $name: got $got want $want"; fi
}

# Distinguishable by binder — must ANSWER, and answer stage0's 42 (3 * 10 + 12).
case_is distinct_binders_forward \
  'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4, 5]\n    return (count x in xs where x > 2) * 10 + (sum y in xs where y > 2)\n' 42
# The reverse order too: keying by line alone made the SECOND query wrong, so one direction
# alone would not have caught it.
case_is distinct_binders_reversed \
  'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4, 5]\n    return (sum y in xs where y > 2) * 10 + (count x in xs where x > 2)\n' 123
# The bool quantifiers share the table; `any` vs `all` is the pair a count cannot expose.
case_is distinct_binders_quantifiers \
  'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3]\n    return 10 if (any a in xs where a > 2) and (all b in xs where b > 0) else 20\n' 10
# Same binder, different keyword — undecidable, must decline.
case_is same_binder_folds \
  'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4, 5]\n    return (count x in xs where x > 2) * 10 + (sum x in xs where x > 2)\n' decline
case_is same_binder_quantifiers \
  'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3]\n    return 10 if (any x in xs where x > 2) and (all x in xs where x > 2) else 20\n' decline
# Same binder, SAME keyword — no ambiguity to resolve, so it must still compile.
case_is same_binder_same_keyword \
  'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4, 5]\n    return (count x in xs where x > 2) * 10 + (count x in xs where x > 4)\n' 31
# One query on a line: the shape that always worked.
case_is single_query \
  'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4, 5]\n    return count x in xs where x > 2\n' 3

if [ "$pass" -ne "$total" ]; then echo "query_head_ambiguity FAILED: passed=$pass total=$total"; exit 1; fi
echo "query_head_ambiguity OK: $pass/$total (per-binder heads resolved; ambiguous heads decline)"
