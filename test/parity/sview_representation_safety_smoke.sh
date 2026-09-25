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

check_bounded_foreign_bytes() {
    local optimization="$1"
    local output="$WORK/bounded-foreign-bytes-O$optimization"
    local log="$output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/repro/sview_bounded_foreign_bytes.elisa" >"$log" 2>&1 || {
        echo "sview representation safety smoke: rejected an explicitly bounded foreign-byte view at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$output" >"$log" 2>&1
    local run_status=$?
    set -e
    [[ "$run_status" -eq 3 ]] || {
        echo "sview representation safety smoke: bounded foreign-byte view returned $run_status at O$optimization, expected 3" >&2
        cat "$log" >&2
        exit 1
    }
}

check_cstr_scan_controls() {
    local optimization="$1"
    local output="$WORK/cstr-scan-controls-O$optimization"
    local log="$output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/repro/cstr_scan_helpers_valid.elisa" >"$log" 2>&1 || {
        echo "sview representation safety smoke: rejected valid C-string scan helpers at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$output" >"$log" 2>&1
    local run_status=$?
    set -e
    [[ "$run_status" -eq 8 ]] || {
        echo "sview representation safety smoke: C-string scan controls returned $run_status at O$optimization, expected 8" >&2
        cat "$log" >&2
        exit 1
    }
}

check_unbounded_cstr_scans_rejected() {
    local optimization="$1"
    local output="$WORK/unbounded-cstr-scans-O$optimization.ll"
    local log="$output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$output" "$ROOT/test/repro/raw_cstr_scan_helpers_reject_unbounded.elisa" >"$log" 2>&1; then
        echo "sview representation safety smoke: accepted raw nullable pointers at C-string scan APIs at O$optimization" >&2
        exit 1
    fi
    for function_name in runtime_strlen strlen string_index string_slice_eq string_slices_eq; do
        rg -Fq "to \"$function_name\" expects cstr, got raw reference" "$log" || {
            echo "sview representation safety smoke: raw pointer to $function_name was not rejected at O$optimization" >&2
            cat "$log" >&2
            exit 1
        }
    done
    [[ ! -e "$output" ]] || {
        echo "sview representation safety smoke: emitted LLVM for rejected raw C-string scans at O$optimization" >&2
        exit 1
    }
}

check_nullable_cstr_contexts_rejected() {
    local optimization="$1"
    local output="$WORK/nullable-cstr-contexts-O$optimization.ll"
    local log="$output.log"
    if "$STAGE1" -emit llvm "-O$optimization" -o "$output" "$ROOT/test/repro/raw_nullable_ref_cstr_contexts_rejected.elisa" >"$log" 2>&1; then
        echo "sview representation safety smoke: accepted raw nullable byte references in cstr? contexts at O$optimization" >&2
        exit 1
    fi
    rg -Fq 'return type expects cstr?, got reference' "$log" || {
        echo "sview representation safety smoke: raw nullable reference return was not rejected at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    rg -Fq 'struct literal field "value" expects cstr, got reference' "$log" || {
        echo "sview representation safety smoke: raw nullable reference field initializer was not rejected at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    [[ "$(rg -F -c 'variable "text" expects cstr?, got reference' "$log")" -eq 2 ]] || {
        echo "sview representation safety smoke: nullable C-string local initialization/rebind checks were incomplete at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    [[ ! -e "$output" ]] || {
        echo "sview representation safety smoke: emitted LLVM for rejected nullable C-string contexts at O$optimization" >&2
        exit 1
    }
}

check_literal_cstr_out_parameter() {
    local optimization="$1"
    local output="$WORK/literal-cstr-out-O$optimization"
    local log="$output.log"
    "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/fixtures/diagnostics/ref_cstr_out_param.neg.elisa" >"$log" 2>&1 || {
        echo "sview representation safety smoke: rejected a terminated literal written through cstr& at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 10 "$output" >"$log" 2>&1
    local run_status=$?
    set -e
    [[ "$run_status" -eq 98 ]] || {
        echo "sview representation safety smoke: literal cstr out-parameter control returned $run_status at O$optimization, expected 98" >&2
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
    reject_case "$optimization" raw-reference-cstr-write-through "$ROOT/test/repro/raw_ref_write_through_cstr_rejected.elisa" 'cannot assign u8& to cstr'
    reject_case "$optimization" raw-pointer-cstr-cast "$ROOT/test/repro/cstr_pointer_cast_probe.elisa" 'can[Unsafe]'
    reject_case "$optimization" raw-reference-cstr-return "$ROOT/test/repro/raw_ref_return_cstr_rejected.elisa" 'return type expects cstr, got reference'
    reject_case "$optimization" nullable-runtime-strlen-unbounded "$ROOT/test/repro/runtime_strlen_unbounded_rejected.elisa" 'expects cstr'
    check_unbounded_cstr_scans_rejected "$optimization"
    check_nullable_cstr_contexts_rejected "$optimization"
    check_safe_literal "$optimization"
    check_typed_view_forwarding "$optimization"
    check_bounded_foreign_bytes "$optimization"
    check_cstr_scan_controls "$optimization"
    check_literal_cstr_out_parameter "$optimization"
done

echo "sview representation safety smoke OK: zeroed and forged StringView carriers, public carrier aliases, unbounded raw sview inputs, and raw-to-cstr conversions are rejected; C-string literal and explicitly bounded foreign-byte views remain valid at O0/O2"
