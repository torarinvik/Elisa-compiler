#!/usr/bin/env bash
# Behavioral smoke for the stage1 MissingReturnValue diagnostic (a non-void function
# whose body does not guarantee a return on all control paths). Exercises the STAGE1
# resolver (via the parse_report harness), mirroring the other parity smokes: the
# check must FIRE on fall-through paths and STAY SILENT on guaranteed-return bodies,
# abort tails (panic/raise), and non-breaking `while true:` loops.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "missing-return smoke FAIL: $1" >&2; exit 1; }

# 1. Fall-through after a guard MUST be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    if n > 0:\n        return 1\n' | "$RPT")
grep -q "may fall through without returning a value" <<< "$out" || fail "guard fall-through not flagged: $out"

# 2. Both-branch return must NOT be flagged.
out=$(printf 'def g(n: i64) -> i64:\n    if n > 0:\n        return 1\n    else:\n        return 0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on both-branch return: $out"

# 3. Void function must NOT be flagged.
out=$(printf 'def v(n: i64) -> void:\n    if n > 0:\n        return\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on void fn: $out"

# 4. Abort tail (`panic(...)`) must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    if n > 0:\n        return 1\n    panic("bad")\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on panic tail: $out"

# 5. A value conditional whose possible arms both panic MUST terminate even when its
# condition is not statically known, and the following statement must be unreachable.
out=$(printf 'def f(flag: bool) -> i64:\n    panic("left") if flag else panic("right")\n    return 0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on two-arm aborting conditional: $out"
grep -q "unreachable code" <<< "$out" || fail "statement after two-arm aborting conditional not flagged: $out"

# 6. An unknown condition with only one aborting arm is not a terminator.
out=$(printf 'def f(flag: bool) -> i64:\n    1 if flag else panic("right")\n' | "$RPT")
grep -q "may fall through without returning a value" <<< "$out" || fail "one-arm aborting conditional hid a fall-through path: $out"

# 7. A value block whose tail panics MUST terminate, and following code is unreachable.
out=$(printf 'def f() -> i64:\n    do:\n        panic("bad")\n    return 0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on panic-only value block: $out"
grep -q "unreachable code" <<< "$out" || fail "statement after panic-only value block not flagged: $out"

# 8. An unconditional terminator before dead statements still terminates the value block.
out=$(printf 'def f() -> i64:\n    do:\n        panic("bad")\n        dead: i64 = 1\n        dead\n    return 0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on panic followed by dead value-block code: $out"
grep -q "unreachable code" <<< "$out" || fail "dead code after panic in value block not flagged: $out"

# 9. Region allocation evaluates its operand, so an aborting operand terminates too.
out=$(printf 'def f() -> i64:\n    region scratch(1024):\n        new[scratch] panic("bad")\n        return 0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting region-allocation operand: $out"
grep -q "unreachable code" <<< "$out" || fail "statement after aborting region-allocation operand not flagged: $out"

# 10. An exhaustive value match whose arms all panic terminates its declaration. Literal
# bool coverage is outside stage0's exhaustiveness subset, so use a wildcard final arm.
out=$(printf 'def f(flag: bool) -> i64:\n    dead: i64 = match flag:\n        true: panic("left")\n        _: panic("right")\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on two-arm aborting match initializer: $out"

# 11. An exhaustive value match with a fall-through wildcard arm is not a terminator.
out=$(printf 'def f(flag: bool) -> i64:\n    dead: i64 = match flag:\n        true: panic("left")\n        _: 1\n' | "$RPT")
grep -q "may fall through without returning a value" <<< "$out" || fail "one-arm aborting match hid a fall-through path: $out"

# 12. Non-breaking `while true:` MUST be flagged -- stage0 treats no loop as a terminator.
# MEASURED 2026-09-16: `elisac -emit obj` on this exact program gives
# "error: function h may fall through without returning a value". This case asserted the
# OPPOSITE until then, against a compiler that had already been corrected to match the oracle
# (see the measured note in src/semantic/resolve_flow_termination.elisa) -- a gate left behind
# by its own fix, red for the wrong reason.
out=$(printf 'def h(n: mutable i64) -> i64:\n    while true:\n        n <- n + 1\n' | "$RPT")
grep -q "may fall through without returning a value" <<< "$out" || fail "while-true not flagged: $out"

# 13. `while true:` WITH a break MUST be flagged (the break path falls through).
out=$(printf 'def h(n: mutable i64) -> i64:\n    while true:\n        break\n' | "$RPT")
grep -q "may fall through without returning a value" <<< "$out" || fail "breaking while-true not flagged: $out"

# 14. Guaranteed final return must NOT be flagged.
out=$(printf 'def k(n: i64) -> i64:\n    return n\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on direct return: $out"

# 15. An aborting if condition terminates before either branch is entered.
out=$(printf 'def f() -> i64:\n    if panic():\n        value: i64 = 1\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting if condition: $out"

# 16. An aborting match scrutinee terminates before a fall-through arm can run.
out=$(printf 'def f() -> i64:\n    match panic():\n        _:\n            value: i64 = 1\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting match scrutinee: $out"

# 17. Loop bodies remain non-terminating for parity, while an aborting condition ends execution.
out=$(printf 'def f() -> i64:\n    while panic():\n        value: i64 = 1\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting while condition: $out"

# 18. A for iterable is evaluated before entering the loop and can abort unconditionally.
out=$(printf 'def f() -> i64:\n    for value in panic():\n        result: i64 = 1\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting for iterable: $out"

# 19-24. Catch/get-else/comprehension wrappers eagerly evaluate their guarded child or
# iterable. Check both expression statements and initializers.
out=$(printf 'def f() -> i64:\n    catch panic():\n        value:\n            value\n        error e:\n            0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting catch child: $out"
out=$(printf 'def f() -> i64:\n    value: i64 = catch panic():\n        result:\n            result\n        error e:\n            0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting catch initializer: $out"
out=$(printf 'def f() -> i64:\n    get panic() else 0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting get-else child: $out"
out=$(printf 'def f() -> i64:\n    value: i64 = get panic() else 0\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting get-else initializer: $out"
out=$(printf 'def f() -> i64:\n    [value for value in panic()]\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting comprehension iterable: $out"
out=$(printf 'def f() -> i64:\n    values: darray[i64] = [value for value in panic()]\n' | "$RPT")
grep -q "may fall through" <<< "$out" && fail "false positive on aborting comprehension initializer: $out"

# 25. Naming the panic function does not invoke it; only `panic(...)` terminates.
out=$(printf 'def f() -> i64:\n    panic\n' | "$RPT")
grep -q "may fall through without returning a value" <<< "$out" || fail "bare panic identifier was treated as a call: $out"

echo "missing-return smoke OK: fall-through/breaking-loop/while-true and one-arm abort conditional flagged; aborting headers and eager wrappers terminate; bare panic value remains non-terminating; both-branch/void/panic-call/value-block/region allocation silent, 0 FP"
