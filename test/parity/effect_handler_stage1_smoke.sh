#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-effect-handler.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if [[ ! -x "$STAGE1" ]]; then
    echo "effect_handler_stage1_smoke SKIP: no stage1 seed at $STAGE1"
    exit 0
fi

run_positive() {
    local fixture="$1"
    local stem="$(basename "$fixture" .elisa)"
    "$ROOT/scripts/elisac_stage1.sh" \
        -emit obj \
        -target-triple wasm32-unknown-unknown \
        -o "$WORK/$stem.o" \
        "$ROOT/test/fixtures/effects/$fixture" \
        >"$WORK/$stem.log" 2>&1
    [[ -s "$WORK/$stem.o" ]] || {
        echo "effect handler output is empty for $fixture" >&2
        exit 1
    }
}

run_zero_overhead_ir() {
    local fixture="$1"
    local stem="$(basename "$fixture" .elisa)"
    "$ROOT/scripts/elisac_stage1.sh" \
        -emit llvm \
        -target-triple wasm32-unknown-unknown \
        -o "$WORK/$stem.ll" \
        "$ROOT/test/fixtures/effects/$fixture" \
        >"$WORK/$stem-llvm.log" 2>&1
    grep -Eq 'call( [^@]*)?@__handler__' "$WORK/$stem.ll" || {
        echo "expected a direct hidden-handler call in LLVM for $fixture" >&2
        sed -n '1,120p' "$WORK/$stem.ll" >&2
        exit 1
    }
    if grep -Eiq 'effect(_|\.)?(handler|dispatch|install)|continuation|resume' "$WORK/$stem.ll"; then
        echo "found runtime effect machinery in zero-overhead LLVM for $fixture" >&2
        exit 1
    fi
}

run_negative() {
    local fixture="$1"
    local expected="$2"
    local stem="$(basename "$fixture" .elisa)"
    if "$ROOT/scripts/elisac_stage1.sh" \
        -emit obj \
        -target-triple wasm32-unknown-unknown \
        -o "$WORK/$stem.o" \
        "$ROOT/test/fixtures/effects/$fixture" \
        >"$WORK/$stem.log" 2>&1; then
        echo "expected effect diagnostic for $fixture" >&2
        exit 1
    fi
    grep -Fq "$expected" "$WORK/$stem.log" || {
        echo "missing expected diagnostic for $fixture: $expected" >&2
        sed -n '1,40p' "$WORK/$stem.log" >&2
        exit 1
    }
}

run_positive "static_handler_bare.elisa"
run_positive "static_handler_capture.elisa"
run_positive "static_handler_scope_named.elisa"
run_positive "static_handler_qualified.elisa"
run_positive "static_handler_qualified_generic.elisa"
run_positive "handler_default_capture.elisa"
run_positive "handler_tail_resume.elisa"
run_positive "nested_handler_forwarding.elisa"
run_positive "nested_handler_capture_forwarding.elisa"
run_positive "static_handler_via.elisa"
run_positive "static_handler_generic_explicit.elisa"
run_positive "handler_via_install.elisa"
run_positive "handler_via_bare_abstract.elisa"
run_positive "handler_target_via.elisa"
run_positive "handler_target_via_forward.elisa"
run_positive "via_grant_covers_both_rows.elisa"
run_positive "via_grant_bare_block.elisa"
run_positive "via_grant_bare_multi_rows.elisa"
run_zero_overhead_ir "static_handler_capture.elisa"
run_zero_overhead_ir "static_handler_scope_named.elisa"
run_zero_overhead_ir "static_handler_qualified.elisa"
run_zero_overhead_ir "static_handler_qualified_generic.elisa"
run_zero_overhead_ir "nested_handler_forwarding.elisa"
run_zero_overhead_ir "nested_handler_capture_forwarding.elisa"
run_zero_overhead_ir "static_handler_generic_explicit.elisa"
run_zero_overhead_ir "handler_via_install.elisa"
run_zero_overhead_ir "handler_via_bare_abstract.elisa"
run_zero_overhead_ir "handler_target_via.elisa"
run_zero_overhead_ir "handler_target_via_forward.elisa"

capture_stem="handler_capture_once"
"$ROOT/scripts/elisac_stage1.sh" \
    -emit llvm \
    -target-triple wasm32-unknown-unknown \
    -o "$WORK/$capture_stem.ll" \
    "$ROOT/test/fixtures/effects/$capture_stem.elisa" \
    >"$WORK/$capture_stem-llvm.log" 2>&1
[[ "$(grep -Ec 'call i64 @make_capture\(' "$WORK/$capture_stem.ll")" == "1" ]] || {
    echo "expected handler capture expression to be evaluated once" >&2
    sed -n '1,160p' "$WORK/$capture_stem.ll" >&2
    exit 1
}
[[ "$(grep -Ec 'call void @__handler__TickHandler__ping' "$WORK/$capture_stem.ll")" == "2" ]] || {
    echo "expected both operations to call the hidden handler directly" >&2
    sed -n '1,160p' "$WORK/$capture_stem.ll" >&2
    exit 1
}
if grep -Eiq 'effect(_|\.)?(handler|dispatch|install)|continuation|resume' "$WORK/$capture_stem.ll"; then
    echo "found runtime effect machinery in zero-overhead LLVM for $capture_stem.elisa" >&2
    exit 1
fi

run_negative "mismatched_handler.neg.elisa" 'effect handler "Wrong" realizes "Other"'
run_negative "missing_operation.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "unhandled_effect.neg.elisa" 'abstract effect operation Tick.ping requires an installed handler'
run_negative "handler_signature_mismatch.neg.elisa" 'handler "Bad" operation "ping" does not match the abstract operation signature'
run_negative "abstract_operation_value.neg.elisa" 'abstract effect operation Tick.ping cannot be used as a value'
run_negative "handler_specialization_call_mismatch.neg.elisa" 'abstract effect operation Writer[sview].write does not match the active handler specialization'
run_negative "handler_qualified_namespace_mismatch.neg.elisa" 'abstract effect operation A::Tick.ping does not match the active handler specialization; runtime effect dispatch is unavailable in the zero-overhead effect subset'
run_negative "handler_specialization_arity.neg.elisa" 'handler "Sink" has invalid specialization of abstract effect "Writer": expected 1 type argument(s), got 2'
run_negative "operation_specialization_arity.neg.elisa" 'abstract effect specialization Writer expects 1 type argument(s), got 2'
run_negative "forward_partial_handler.neg.elisa" 'abstract effect operation Tick.ping requires an installed handler'
run_negative "unknown_abstract_operation_row.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "unknown_abstract_operation_call.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "operation_effect_row.neg.elisa" 'abstract effect row "Tick.ping" names operation "ping"; effect rows must name the family "Tick"'
run_negative "handler_operation_target_row.neg.elisa" 'abstract effect row "Tick.ping" names operation "ping"; effect rows must name the family "Tick"'
run_negative "via_operation_effect_row.neg.elisa" 'abstract effect row "Tick.ping via Console.Write" names operation "ping"; effect rows must name the family "Tick"'
run_negative "duplicate_abstract_operation.neg.elisa" 'effect "Tick" declares operation "ping" more than once'
run_negative "duplicate_handler_operation.neg.elisa" 'effect handler "Bad" declares operation "ping" more than once'
run_negative "via_unknown_abstract.neg.elisa" 'abstract effect family "Missing" is not declared'
run_negative "via_unknown_permission.neg.elisa" 'concrete effect permission "NoSuch.Write" names unknown permission family "NoSuch"'
run_negative "handler_target_via_unknown_permission.neg.elisa" 'concrete effect permission "NoSuch.Write" names unknown permission family "NoSuch"'
run_negative "permission_member_mismatch.neg.elisa" 'permission "LocalConsole" has no member "Read"'
run_negative "handler_implementation_access.neg.elisa" 'compiler-generated static effect operation "__handler__H__ping" is private'
run_negative "handler_capture_arity.neg.elisa" 'effect handler "Sink" requires 1 capture argument(s), got 0'
run_negative "handler_nested_resume.neg.elisa" 'handler "Bad" operation "ping" is outside the zero-overhead resumable subset'

echo "effect handler stage1 smoke OK: handled effects, captures, nesting, resume, via permissions, and diagnostics are stable"
