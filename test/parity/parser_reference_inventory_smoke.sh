#!/usr/bin/env bash
# Keep the parser-parity denominator tied to the stage0 oracle and prove every
# stage0 parser test that actually invokes parsing emits at least one replay case.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
PARSER_DIR="$ELISA_CORE/compiler/src/parser"

[[ -d "$PARSER_DIR" ]] || {
    echo "parser reference inventory FAILED: missing $PARSER_DIR" >&2
    exit 1
}

test_count="$(rg -n '^func Test' "$PARSER_DIR" --glob '*_test.go' | wc -l | tr -d ' ')"
source_count="$(rg --files "$PARSER_DIR" --glob '*.go' | wc -l | tr -d ' ')"
[[ "$test_count" -gt 0 && "$source_count" -gt 0 ]] || {
    echo "parser reference inventory FAILED: tests=$test_count sources=$source_count" >&2
    exit 1
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ORACLE="$WORK/oracle.tsv"
(cd "$ELISA_CORE/compiler" && ELISA_PARSER_PARITY_OUT="$ORACLE" go test ./src/parser -count=1 >/dev/null)

rg -n '^func Test[^ (]+' "$PARSER_DIR" --glob '*_test.go' -o \
    | sed -E 's/.*func (Test[^ (]+).*/\1/' | sort -u > "$WORK/all.txt"
cut -f1 "$ORACLE" | sed 's#/.*##' | sort -u > "$WORK/recorded.txt"
comm -23 "$WORK/all.txt" "$WORK/recorded.txt" > "$WORK/unrecorded.txt"

# These tests do not parse source: one constructs an AST manually for the unparser,
# one constructs a machine arm directly, and one feeds a token stream directly to
# the permission-reference estimator. Every other parser-package test must hit the
# recorder.
printf '%s\n' \
    TestEstimateCommaSeparatedCountStopsAtColon \
    TestFormatCallWithDoExprBlockArg \
    TestMachineTransitionCopiesShadowingArmLocal \
    TestUnbracketedPermissionRefsDoNotEstimateToEOF \
    > "$WORK/non_parser_tests.txt"
if ! diff -u "$WORK/non_parser_tests.txt" "$WORK/unrecorded.txt" >/dev/null; then
    echo "parser reference inventory FAILED: unrecorded parser tests changed:" >&2
    diff -u "$WORK/non_parser_tests.txt" "$WORK/unrecorded.txt" >&2 || true
    exit 1
fi

recorded_test_count="$(wc -l < "$WORK/recorded.txt" | tr -d ' ')"
case_count="$(wc -l < "$ORACLE" | tr -d ' ')"
echo "parser reference inventory OK: $recorded_test_count/$test_count parsing tests recorded as $case_count cases across $source_count Go files (4 non-source-parser tests)" >&2
