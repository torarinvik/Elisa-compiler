#!/usr/bin/env bash
# Two-compiler parity for the GUARDED-RETURN slice of the `ensure` prover.
#
# stage0 discharges an `ensure` per RETURN PATH with the path condition as a known fact, so
#   def f(n: i64) -> i64:
#       ensure result == n + 3
#       if n == 0:
#           return 2
#       return n + 3
# draws one diagnostic AT THE `return 2` LINE. stage1's main prover only judges a single
# straight-line return, so every shape like this went unreported; check_ensure_strict_guarded_
# return.elisa closes the decidable slice of that gap. This smoke pins the two things a
# count-only oracle cannot see: the LINE stage0 anchors at, and the boundaries of the rule --
# a guard that contradicts `requires`/`where` is DEAD code and must stay silent, and two
# refuting guards draw two diagnostics, not one.
#
# stage1 reads the case through the reporter, which needs the `# strict` header to enable the
# strict-proof checks stage0's CLI turns on by default; the header is a comment to stage0, so
# both compilers see the same file and the line numbers line up.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
checked=0

# `LINE|message` for every diagnostic whose sentence mentions a proof obligation, from each
# compiler, sorted. stage0 prints `path:LINE:col-col: message`; stage1 prints `  L<LINE> message`
# two lines lower, because of the header.
stage0_pairs() {
    "$ELISACORE_BIN" -emit semantic "$1" 2>&1 >/dev/null \
        | grep -E ':[0-9]+:[0-9]+' \
        | sed -E 's#^[^:]*:([0-9]+):[0-9]+(-[0-9]+(:[0-9]+)?)?: #\1|#' \
        | sort
}

stage1_pairs() {
    { printf '# strict\n# smt\n'; cat "$1"; } > "$WORK/cased.txt"
    "$REPO_ROOT/build/parse_report" < "$WORK/cased.txt" \
        | awk '/^D [0-9]+$/{d=1; next} d && match($0, /^  L[0-9]+ /){printf "%d|%s\n", substr($0, 4, RLENGTH - 4) - 2, substr($0, RLENGTH + 1)}' \
        | sort
}

check_case() {
    local name="$1" source="$2"
    checked=$((checked + 1))
    printf '%s' "$source" > "$WORK/$name.elisa"
    local s0 s1
    s0="$(stage0_pairs "$WORK/$name.elisa")"
    s1="$(stage1_pairs "$WORK/$name.elisa")"
    if [ "$s0" != "$s1" ]; then
        failed=$((failed + 1))
        printf 'ensure guarded-return mismatch: %s\n  stage0: %s\n  stage1: %s\n' \
            "$name" "${s0//$'\n'/ ; }" "${s1//$'\n'/ ; }" >&2
    fi
}

# The shape the gap was found on: a recursive affine function whose base case refutes the
# postcondition. stage0 reports TWO diagnostics -- the declined recursive proof at the call,
# and the refuted goal at `return 2`.
check_case recursive_base $'def rec(n: i64) -> i64:\n    requires n >= 0\n    ensure result == n + 3\n    decreases n\n    if n == 0:\n        return 2\n    return rec(n - 1) + 1\n'

# The same refutation without recursion, and with an `else:` arm -- the guarded path is judged
# on its own whatever the other arm does.
check_case plain_branch $'def f(n: i64) -> i64:\n    ensure result == n + 3\n    if n == 0:\n        return 2\n    return n + 3\n'
check_case else_arm     $'def f(n: i64) -> i64:\n    ensure result == n + 3\n    if n == 0:\n        return 2\n    else:\n        return n + 3\n    return 0\n'

# An inequality goal refutes the same way.
check_case inequality $'def f(n: i64) -> i64:\n    requires n >= 0\n    ensure result >= n\n    if n == 5:\n        return 1\n    return n\n'

# TWO refuting guards draw TWO diagnostics, one per return.
check_case two_guards $'def f(n: i64) -> i64:\n    ensure result == n + 3\n    if n == 0:\n        return 2\n    if n == 1:\n        return 9\n    return n + 3\n'

# A guard the contracts rule out is DEAD code: stage0 discharges the obligation vacuously and
# says nothing. Firing here would be a pure over-report, so the rule vetoes the path when the
# pin contradicts a `requires` clause, a compound one, or a parameter `where` refinement.
check_case dead_requires   $'def f(n: i64) -> i64:\n    requires n > 0\n    ensure result == n + 3\n    if n == 0:\n        return 2\n    return n + 3\n'
check_case dead_compound   $'def f(n: i64) -> i64:\n    requires n >= 0 and n <= 10\n    ensure result == n + 3\n    if n == 20:\n        return 2\n    return n + 3\n'
check_case dead_refinement $'def f(n: i64 where n > 0) -> i64:\n    ensure result == n + 3\n    if n == 0:\n        return 2\n    return n + 3\n'

# A guard inside the contracts' reach that HOLDS proves the goal: both compilers stay silent.
check_case provable_guard $'def f(n: i64) -> i64:\n    ensure result == n + 3\n    if n == 0:\n        return 3\n    return n + 3\n'
check_case provable_rec   $'def rec(n: i64) -> i64:\n    requires n >= 0\n    ensure result == n + 2\n    decreases n\n    if n == 0:\n        return 2\n    return rec(n - 1) + 1\n'

if [ "$failed" -ne 0 ]; then
    echo "ensure guarded-return smoke FAILED: $failed/$checked cases disagree" >&2
    exit 1
fi
echo "ensure guarded-return smoke OK: $checked/$checked cases agree with stage0"
