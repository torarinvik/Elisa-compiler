#!/usr/bin/env bash
# Compare secondary invalid-callee diagnostics with Stage0. An already-invalid
# callee should not produce an additional call error, while genuinely non-callable
# values are checked separately. The cases retain coverage for private members,
# unknown names, generic applications, poisoned arguments, and ambiguous calls.
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

# Poisoned callees: compare whether a secondary diagnostic is emitted.
check_case private_member $'module Api:\n    private:\n        def hidden() -> i64:\n            return 1\n\nusing Api\n\ndef use() -> i64:\n    return Api::hidden()\n'
check_case undefined_callee $'def use() -> i64:\n    return baz()\n'
check_case ufcs_nonconforming $'struct Bare:\n    y: i64\n\nprotocol Eq:\n    def eq(self: Self, other: Self) -> bool\n\ndef same(a: Bare, b: Bare) -> bool:\n    return a.eq(b)\n'
check_case generic_bound $'struct Bare:\n    y: i64\n\nprotocol Comparable:\n    type Item\n    def lt(a: Item, b: Item) -> bool\n\ndef max_of[T: Comparable](a: T, b: T) -> T:\n    if a.lt(b):\n        return b\n    return a\n\ndef use() -> Bare:\n    p: Bare = Bare{y: 1}\n    q: Bare = Bare{y: 2}\n    return max_of[Bare](p, q)\n'
check_case field_on_param $'protocol Eq:\n    def lt(a: Self, b: Self) -> bool\n\ndef m[T](a: T) -> bool:\n    return a.lt(a)\n'
# A generic application with MORE THAN ONE type argument is a different AST node than
# the single-argument one; it carried no cascade until IndexN was handled too.
check_case generic_multi_type_arg $'def f(x: i64) -> void:\n    _ = nosuch_generic[i64, i64](x, 16)\n'
check_case generic_one_type_arg $'def f(x: i64) -> void:\n    y: i64 = nosuch_generic[i64](x)\n'

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
