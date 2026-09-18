#!/usr/bin/env bash
# Two-compiler parity for the OPERATOR diagnostics stage0 raises over an `<invalid>` operand.
#
# A name stage0 cannot resolve is typed `<invalid>`, and an arithmetic or ordering operator
# over such an operand draws a SECOND diagnostic on the same line:
#   error: undefined identifier "nosuch"
#   error: operator requires numeric operands
# stage1 reported only the first. check_poisoned_operand.elisa adds the second; this smoke
# pins both halves of the rule -- the operators that must carry it, and the ones that must
# not, where equality tolerates `<invalid>` and a RESOLVED call's return type is known
# whatever its arguments are.
#
# Only these two sentences are compared: the fixtures deliberately also carry the poisoning
# error, and pinning the whole message set here would duplicate diagnostics_diff.sh.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
checked=0

# Both sentences at once, each line tagged with which one it is, so a rule that fires the
# WRONG one of the two still shows up as a mismatch rather than cancelling out.
check_case() {
    local name="$1" source="$2"
    checked=$((checked + 1))
    printf '%s' "$source" > "$WORK/$name.elisa"
    local s0 s1
    s0="$("$ELISACORE_BIN" -emit semantic "$WORK/$name.elisa" 2>&1 >/dev/null \
        | grep -E 'operator requires numeric operands|comparison requires numeric operands' \
        | sed -E 's#^[^:]*:([0-9]+):[0-9]+[^ ]* (operator|comparison) .*#\2 \1#' | sort)"
    s1="$("$REPO_ROOT/build/parse_report" < "$WORK/$name.elisa" \
        | grep -E 'operator requires numeric operands|comparison requires numeric operands' \
        | sed -E 's#^  L([0-9]+) (operator|comparison) .*#\2 \1#' | sort)"
    if [ "$s0" != "$s1" ]; then
        failed=$((failed + 1))
        printf 'poisoned-operand mismatch: %s\n  stage0: %s\n  stage1: %s\n' \
            "$name" "${s0//$'\n'/ | }" "${s1//$'\n'/ | }" >&2
    fi
}

# FIRES: an operand stage0 types `<invalid>`.
check_case arith_undefined $'def f(x: i64) -> i64:\n    return nosuch + 1\n'
check_case ordering_undefined $'def f(x: i64) -> bool:\n    return nosuch > other_missing\n'
check_case nested_arith $'def f(x: i64) -> i64:\n    return nosuch - missing2 * other3\n'
check_case modulo $'def f(x: i64) -> i64:\n    return nosuch % 2\n'
check_case shift $'def f(x: i64) -> i64:\n    return nosuch << 2\n'
check_case bitand $'def f(x: i64) -> i64:\n    return nosuch & 2\n'
check_case condition $'def f(x: i64) -> bool:\n    if nosuch > 0:\n        return true\n    return false\n'
check_case unknown_field $'struct S:\n    a: i64\n\ndef f(s: S) -> i64:\n    return s.nofield + 1\n'
check_case field_on_primitive $'def f(x: i64) -> i64:\n    return x.nofield + 1\n'
check_case private_call $'module Api:\n    public:\n        def visible() -> i64:\n            return 1\n    private:\n        def hidden() -> i64:\n            return 2\n\nusing Api\n\ndef f() -> i64:\n    return Api::visible() + Api::hidden()\n'

# SILENT: stage0 raises nothing beyond the poisoning error itself.
check_case equality $'def f(x: i64) -> bool:\n    return x == nosuch\n'
check_case inequality $'def f(x: i64) -> bool:\n    return x != nosuch\n'
check_case resolved_call $'def g(x: i64) -> i64:\n    return x\n\ndef f(x: i64) -> i64:\n    return g(nosuch) + 1\n'
check_case clean $'def f(x: i64) -> i64:\n    return x + 1\n'

if [ "$failed" -ne 0 ]; then
    printf 'poisoned-operand smoke FAILED: %d/%d cases disagree\n' "$failed" "$checked" >&2
    exit 1
fi
printf 'poisoned-operand smoke OK: %d/%d cases agree with stage0\n' "$checked" "$checked"
