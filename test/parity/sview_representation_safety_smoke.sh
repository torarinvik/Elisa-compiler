#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "sview representation safety smoke: missing Stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-representation.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

reject_case() {
    local optimization="$1" name="$2" source="$3" expected="$4"
    local output="$WORK/$name-O$optimization.ll"
    local log="$output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$output" "$source" >"$log" 2>&1; then
        echo "sview representation safety smoke: accepted $name at O$optimization" >&2
        exit 1
    fi
    rg -Fq "$expected" "$log" || {
        echo "sview representation safety smoke: $name was rejected for the wrong reason at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    [[ ! -e "$output" ]] || {
        echo "sview representation safety smoke: emitted LLVM for rejected $name at O$optimization" >&2
        exit 1
    }
}

check_safe_literal() {
    local optimization="$1"
    local output="$WORK/safe-literal-O$optimization"
    local log="$output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/parity/fixtures/sview_safe_literal.elisa" >"$log" 2>&1 || {
        echo "sview representation safety smoke: rejected the NUL-terminated literal control at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$output" >"$log" 2>&1
    local run_status=$?
    set -e
    [[ "$run_status" -eq 3 ]] || {
        echo "sview representation safety smoke: safe literal control returned $run_status at O$optimization, expected 3" >&2
        cat "$log" >&2
        exit 1
    }
}

check_typed_view_forwarding() {
    local optimization="$1"
    local output="$WORK/typed-view-forward-O$optimization"
    local log="$output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/repro/sview_typed_parameter_forward.elisa" >"$log" 2>&1 || {
        echo "sview representation safety smoke: rejected typed sview parameter forwarding at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$output" >"$log" 2>&1
    local run_status=$?
    set -e
    [[ "$run_status" -eq 3 ]] || {
        echo "sview representation safety smoke: typed sview forwarding returned $run_status at O$optimization, expected 3" >&2
        cat "$log" >&2
        exit 1
    }
}

for optimization in 0 2; do
    reject_case "$optimization" zeroed-view "$ROOT/test/repro/sview_zeroed_invalid.elisa" 'sview with valid backing'
    reject_case "$optimization" zeroed-view-alias "$ROOT/test/repro/sview_zeroed_alias_invalid.elisa" 'sview with valid backing'
    reject_case "$optimization" forged-view-extent "$ROOT/test/repro/sview_extent_overrun.elisa" 'internal runtime carrier type "StringView"'
    reject_case "$optimization" public-view-alias "$ROOT/test/repro/sview_private_alias_probe.elisa" 'internal runtime carrier type "StringView"'
    reject_case "$optimization" unterminated-sview-input "$ROOT/test/repro/sview_unterminated_input.elisa" 'expects NUL-terminated cstr, got raw reference'
    reject_case "$optimization" raw-reference-cstr-argument "$ROOT/test/repro/cstr_pointer_coercion_probe.elisa" 'expects cstr, got raw reference'
    reject_case "$optimization" raw-reference-cstr-assignment "$ROOT/test/repro/cstr_pointer_assignment_probe.elisa" 'expects cstr, got reference'
    reject_case "$optimization" raw-pointer-cstr-cast "$ROOT/test/repro/cstr_pointer_cast_probe.elisa" 'can[Unsafe]'
    check_safe_literal "$optimization"
    check_typed_view_forwarding "$optimization"
done

echo "sview representation safety smoke OK: zeroed and forged StringView carriers, public carrier aliases, unbounded raw sview inputs, and raw-to-cstr conversions are rejected; a C-string literal view remains valid at O0/O2"
