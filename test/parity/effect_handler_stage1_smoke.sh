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
run_positive "handler_tail_resume.elisa"
run_positive "nested_handler_forwarding.elisa"
run_positive "static_handler_via.elisa"
run_positive "static_handler_generic_explicit.elisa"
run_zero_overhead_ir "static_handler_capture.elisa"
run_zero_overhead_ir "nested_handler_forwarding.elisa"
run_zero_overhead_ir "static_handler_generic_explicit.elisa"

run_negative "mismatched_handler.neg.elisa" 'effect handler "Wrong" realizes "Other"'
run_negative "missing_operation.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "unhandled_effect.neg.elisa" 'abstract effect operation Tick.ping requires an installed handler'
run_negative "handler_signature_mismatch.neg.elisa" 'handler "Bad" operation "ping" does not match the abstract operation signature'
run_negative "abstract_operation_value.neg.elisa" 'abstract effect operation Tick.ping cannot be used as a value'
run_negative "handler_specialization_call_mismatch.neg.elisa" 'abstract effect operation Writer[sview].write does not match the active handler specialization'

echo "effect handler stage1 smoke OK: handled effects, captures, nesting, resume, via permissions, and diagnostics are stable"
