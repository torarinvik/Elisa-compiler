#!/usr/bin/env bash
# Linear proof normalization must decline overflowing extrema, never trap or wrap them into proof.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/assert_by_min_i64.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -eq 0 || "$status" -ge 128 ]]; then
    printf 'assert-by MIN_I64 regression: expected a normal diagnostic exit, got %s\n%s\n' "$status" "$output" >&2
    exit 1
fi
if [[ "$output" != *"could not be proven"* && "$output" != *"unproven"* ]]; then
    printf 'assert-by MIN_I64 regression: missing proof diagnostic\n%s\n' "$output" >&2
    exit 1
fi

echo "assert-by MIN_I64 smoke OK: overflowing linear extremum declined without a trap"
