#!/usr/bin/env bash
# Prove every stage0 end-to-end semantic test reaches the shared oracle recorder.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
TEST_DIR="$ELISA_CORE/compiler/test/semantic"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ORACLE="$WORK/oracle.tsv"

test_count="$(rg -n '^func Test' "$TEST_DIR" --glob '*_test.go' | wc -l | tr -d ' ')"
(cd "$ELISA_CORE/compiler" && ELISA_SEMANTIC_PARITY_OUT="$ORACLE" go test ./test/semantic -count=1 >/dev/null 2>&1) || true

rg -n '^func Test[^ (]+' "$TEST_DIR" --glob '*_test.go' -o \
    | sed -E 's/.*func (Test[^ (]+).*/\1/' | sort -u > "$WORK/all.txt"
cut -f1 "$ORACLE" | sed 's#/.*##' | sort -u > "$WORK/recorded.txt"
comm -23 "$WORK/all.txt" "$WORK/recorded.txt" > "$WORK/unrecorded.txt"
if [[ -s "$WORK/unrecorded.txt" ]]; then
    echo "semantic reference inventory FAILED: tests bypassing the oracle recorder:" >&2
    cat "$WORK/unrecorded.txt" >&2
    exit 1
fi

case_count="$(wc -l < "$ORACLE" | tr -d ' ')"
echo "semantic reference inventory OK: $test_count/$test_count end-to-end tests recorded as $case_count cases" >&2
