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

run_negative "mismatched_handler.neg.elisa" 'effect handler "Wrong" realizes "Other"'
run_negative "missing_operation.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "unhandled_effect.neg.elisa" 'abstract effect operation Tick.ping requires an installed handler'

echo "effect handler stage1 smoke OK: handled effects, captures, nesting, resume, via permissions, and diagnostics are stable"
