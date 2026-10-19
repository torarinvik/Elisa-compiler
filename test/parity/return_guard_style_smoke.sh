#!/usr/bin/env bash
# Canonical return-first guards, the legacy style hint, and boolean typing of
# multiline postfix guards (including loop control forms).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "return-guard smoke FAIL: $1" >&2; exit 1; }
report() { printf '%s' "$1" | "$RPT"; }
require_clean_parse() {
    grep -q '^P 0$' <<< "$1" || fail "$2 did not parse cleanly: $1"
}

canonical_source=$'def canonical(done: bool) -> i64:\n    return 1 if done\n    return 0\n'
canonical_output="$(report "$canonical_source")"
require_clean_parse "$canonical_output" "return-first guard"
grep -Fq 'prefer `return value if condition` to `value return if condition`' <<< "$canonical_output" && \
    fail "canonical return-first spelling received the style hint: $canonical_output"

legacy_source=$'def legacy(done: bool) -> i64:\n    1 return if done\n    return 0\n'
legacy_output="$(report "$legacy_source")"
require_clean_parse "$legacy_output" "value-first guard"
grep -Fq 'prefer `return value if condition` to `value return if condition`' <<< "$legacy_output" || \
    fail "legacy value-first spelling did not receive the style hint: $legacy_output"

block_source=$'def guarded(left: bool, right: bool) -> i64:\n    return 1 if:\n        left\n        right\n    for i in 0..<1:\n        continue if:\n            left\n            right\n    for i in 0..<1:\n        break if:\n            left\n            right\n    return 0\n'
block_output="$(report "$block_source")"
require_clean_parse "$block_output" "multiline return/break/continue guards"
grep -Eq 'logical operator requires bool operands|if condition must be bool' <<< "$block_output" && \
    fail "boolean guard expressions were rejected: $block_output"

nonbool_source=$'def invalid(left: bool, right: i64) -> i64:\n    return 1 if:\n        left\n        right\n    return 0\n'
nonbool_output="$(report "$nonbool_source")"
require_clean_parse "$nonbool_output" "non-boolean multiline guard"
grep -Fq 'logical operator requires bool operands' <<< "$nonbool_output" || \
    fail "non-boolean guard expression was not rejected: $nonbool_output"

echo "return-guard smoke OK: canonical style, legacy hint, bool-checked block guards, break/continue"
