#!/usr/bin/env bash
# Two-compiler parity for the CASCADE after a call with an unresolvable callee.
#
# stage0 types such a callee `<invalid>` and reports the call itself in addition to the
# error that poisoned it, so a private call draws two diagnostics on one line:
#   error: "Api.hidden" is private to module "Api"
#   error: cannot call non-function value of type <invalid>
# stage1 reported only the first. check_call_of_invalid.elisa adds the second from stage1's
# own diagnostics; this smoke pins BOTH halves of the rule -- the lines that must carry the
# cascade, and the lines that must NOT, where the poisoned name is an ARGUMENT rather than
# the callee, or where an ambiguous UFCS call resolved to candidates instead of nothing.
#
# Only the cascade sentence is compared: these fixtures deliberately also carry the
# poisoning error, and pinning the whole message set here would turn this into a second
# copy of diagnostics_diff.sh.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

SENTENCE='cannot call non-function value of type <invalid>'
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
        | grep -F "$SENTENCE" | sed -E 's#^[^:]*:([0-9]+):.*#\1#' | sort)"
    s1="$("$REPO_ROOT/build/parse_report" < "$WORK/$name.elisa" \
        | grep -F "$SENTENCE" | sed -E 's#^  L([0-9]+) .*#\1#' | sort)"
    if [ "$s0" != "$s1" ]; then
        failed=$((failed + 1))
        printf 'invalid-call cascade mismatch: %s\n  stage0 lines: %s\n  stage1 lines: %s\n' \
            "$name" "${s0//$'\n'/ }" "${s1//$'\n'/ }" >&2
    fi
}

# FIRES: the callee itself is what another diagnostic poisoned.
check_case private_member $'module Api:\n    private:\n        def hidden() -> i64:\n            return 1\n\nusing Api\n\ndef use() -> i64:\n    return Api::hidden()\n'
check_case undefined_callee $'def use() -> i64:\n    return baz()\n'
check_case ufcs_nonconforming $'struct Bare:\n    y: i64\n\nprotocol Eq:\n    def eq(self: Self, other: Self) -> bool\n\ndef same(a: Bare, b: Bare) -> bool:\n    return a.eq(b)\n'
check_case generic_bound $'struct Bare:\n    y: i64\n\nprotocol Comparable:\n    type Item\n    def lt(a: Item, b: Item) -> bool\n\ndef max_of[T: Comparable](a: T, b: T) -> T:\n    if a.lt(b):\n        return b\n    return a\n\ndef use() -> Bare:\n    p: Bare = Bare{y: 1}\n    q: Bare = Bare{y: 2}\n    return max_of[Bare](p, q)\n'
check_case field_on_param $'protocol Eq:\n    def lt(a: Self, b: Self) -> bool\n\ndef m[T](a: T) -> bool:\n    return a.lt(a)\n'

# SILENT: the poisoned name is an ARGUMENT, not the callee.
check_case poisoned_argument $'struct Header:\n    a: i64\n\ndef use() -> usize:\n    return offset_of(Header, missing)\n'
check_case undefined_receiver $'effect Tick:\n    def ping() -> void\n\ndef main() -> void:\n    Tick.ping()\n'

# SILENT: an ambiguous UFCS call resolved to candidates, so stage0 has a type to talk about.
check_case ufcs_ambiguous $'module left:\n    struct Box:\n        value: i64\n\n    def score(box: Box) -> i64:\n        return box.value\n\nmodule right:\n    def score(box: left::Box) -> i64:\n        return box.value + 1\n\nusing left\nusing right\n\ndef read(box: Box) -> i64:\n    return box.score()\n'

# SILENT: a call that resolves cleanly.
check_case resolved_call $'def helper() -> i64:\n    return 1\n\ndef use() -> i64:\n    return helper()\n'

if [ "$failed" -ne 0 ]; then
    echo "invalid-call cascade smoke FAILED: $failed/$checked cases disagree" >&2
    exit 1
fi
echo "invalid-call cascade smoke OK: $checked/$checked cases agree with stage0"
