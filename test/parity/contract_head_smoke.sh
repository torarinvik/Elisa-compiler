#!/usr/bin/env bash
# Two-compiler parity for the CONTRACT-HEAD lookahead.
#
# stage0 decides `requires`/`ensure`/`invariant`/`decreases` with an EXCLUSION list
# (looksLikeContractStmt): the word opens a contract clause UNLESS the next token ends the
# line or begins a binding (`=`, `:`, `<-`), which are the only shapes in which an ordinary
# local of that name can be written. stage1 used to list the expression STARTS it would
# accept, so a clause opening with anything else -- `requires -n <= 0`, `decreases -n`,
# `requires [a, b].count > 0` -- silently parsed as an expression statement: the contract
# was DROPPED and an `undefined identifier "requires"` invented in its place.
#
# Both symptoms of that mis-parse are pinned here, on both compilers: the invented
# identifier, and the `expression statement has no effect` that follows it. The clause's
# PROOF behaviour is deliberately not compared -- stage0's CLI enables strict proofs and
# parse_report does not, so an `ensure` that is parsed correctly still reports differently.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

MISPARSE='undefined identifier "(requires|ensure|ensures|invariant|decreases|uses)"|expression statement has no effect'
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
checked=0

check_case() {
    local name="$1" source="$2"
    checked=$((checked + 1))
    printf '%s' "$source" > "$WORK/$name.elisa"
    local s0 s1
    s0="$("$ELISACORE_BIN" -emit semantic "$WORK/$name.elisa" 2>&1 >/dev/null \
        | grep -E "$MISPARSE" | sed -E 's#^[^:]*:([0-9]+):[^ ]* #\1 #' | sort)"
    s1="$("$REPO_ROOT/build/parse_report" < "$WORK/$name.elisa" \
        | grep -E "$MISPARSE" | sed -E 's#^  L([0-9]+) #\1 #' | sort)"
    if [ "$s0" != "$s1" ]; then
        failed=$((failed + 1))
        printf 'contract-head mismatch: %s\n  stage0: %s\n  stage1: %s\n' \
            "$name" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
    fi
}

# A contract clause whose expression does not start with an identifier or a literal.
check_case requires_negated $'def f(n: i64) -> i64:\n    requires -n <= 0\n    return n\n'
check_case ensure_negated $'def f(n: i64) -> i64:\n    ensure -result <= 0\n    return n\n'
check_case invariant_negated $'def f(x: i64) -> i64:\n    invariant -x < 1\n    return x\n'
check_case decreases_negated $'def count_up(n: i64) -> i64:\n    requires n <= 0\n    decreases -n\n    if n == 0:\n        return 0\n    return count_up(n + 1)\n'
check_case requires_list_literal $'def f(n: i64) -> i64:\n    requires [n, 1].count > 0\n    return n\n'

# The exclusion list is what keeps an ordinary local of the same name working: the next
# token binds it, so the word is NOT a contract head.
check_case local_named_requires $'def f(x: i64) -> i64:\n    requires = 5\n    return requires + x\n'
check_case local_named_requires_typed $'def f(x: i64) -> i64:\n    requires: i64 = 5\n    return requires + x\n'
check_case local_named_ensure_rebound $'def f(x: i64) -> i64:\n    ensure: mutable i64 = 5\n    ensure <- 6\n    return ensure + x\n'

# Still a contract clause in the shapes stage1 already accepted.
check_case requires_plain $'def f(n: i64) -> i64:\n    requires n > 0\n    return n\n'
check_case uses_unknown $'def f(x: i64) -> i64:\n    uses GhostContract(x)\n    return x\n'

if [ "$failed" -ne 0 ]; then
    printf 'contract-head smoke FAILED: %d/%d cases disagree\n' "$failed" "$checked" >&2
    exit 1
fi
printf 'contract-head smoke OK: %d/%d cases agree with stage0\n' "$checked" "$checked"
