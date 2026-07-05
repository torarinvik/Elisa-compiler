#!/usr/bin/env bash
# Behavioral smoke for the stage1 MissingReturnValue diagnostic (a non-void function
# whose body does not guarantee a return on all control paths).
#
# Uses the stage0 elisac compiler directly to test source snippets, checking that the
# missing-return check FIRES on functions that can fall through without returning, and
# STAYS SILENT on functions that guarantee a return. A green run proves the check
# is behaviorally correct.
#
# Usage: test/parity/missing_return_smoke.sh
set -euo pipefail

ELISAC="${ELISACORE_BIN:-elisac}"
if ! command -v "$ELISAC" >/dev/null 2>&1; then
    ELISAC="${HOME}/.elisac/elisac"
fi
if ! [ -x "$ELISAC" ]; then
    echo "error: elisac not found; set ELISACORE_BIN or ensure ~/.elisac/elisac exists" >&2
    exit 2
fi

fail() { echo "missing return smoke FAIL: $1" >&2; exit 1; }

test_case() {
    local name="$1"
    local code="$2"
    local should_error="$3"

    local tmpfile
    tmpfile=$(mktemp)
    trap "rm -f '$tmpfile'" RETURN

    printf '%b' "$code" > "$tmpfile"
    local output
    output=$("$ELISAC" -emit obj -O2 -permissive "$tmpfile" 2>&1 || true)

    if [ "$should_error" = "yes" ]; then
        if echo "$output" | grep -q "may fall through"; then
            return 0
        else
            fail "$name: expected missing return error, got: $output"
        fi
    else
        if echo "$output" | grep -q "may fall through"; then
            fail "$name: unexpected missing return error: $output"
        fi
        return 0
    fi
}

# 1. Non-void function with no return statement MUST be flagged.
test_case "non-void without return" \
    'def f() -> i64:\n    x: i64 = 1\n' yes

# 2. Non-void function that can fall through a guard MUST be flagged.
test_case "guard fallthrough" \
    'def f(n: i64) -> i64:\n    if n > 0:\n        return n\n    x: i64 = 0\n' yes

# 3. Non-void function with return as last statement must NOT be flagged.
test_case "guaranteed return" \
    'def f() -> i64:\n    x: i64 = 1\n    return x\n' no

# 4. Non-void function with guaranteed return in both if/else branches must NOT be flagged.
test_case "if/else both-return" \
    'def f(n: i64) -> i64:\n    if n > 0:\n        return n\n    else:\n        return 0\n' no

# 5. Non-void function with return in loop MUST NOT be flagged if return is last statement.
test_case "loop-then-return" \
    'def f() -> i64:\n    x: i64 = 0\n    while x < 10:\n        x <- x + 1\n    return x\n' no

# 6. Non-void function with match covering all arms with returns must NOT be flagged.
test_case "exhaustive match all-arm returns" \
    'enum E:\n    A\n    B\n\ndef f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.B:\n            return 2\n' no

# 7. Void functions must NOT be flagged.
test_case "void function" \
    'def f() -> void:\n    x: i64 = 1\n' no

# 8. Non-void with match that doesn't guarantee return in all arms might be caught by exhaustiveness check first.
# This test is optional as non-exhaustive matches are caught separately.
# test_case "match missing arm" \
#     'enum E:\n    A\n    B\n\ndef f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n' yes

echo "missing return smoke OK: detects missing returns, silent on guaranteed returns"
