#!/usr/bin/env bash
# An unbounded invariant side spans all of i64; narrowing it invents false violations.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/invariant_full_i64_interval.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
    printf 'full-i64 invariant regression: expected an unknown-but-valid call, got %s\n%s\n' "$status" "$output" >&2
    exit 1
fi
if [[ "$output" == *"provably does not satisfy"* ]]; then
    printf 'full-i64 invariant regression: truncated interval manufactured a violation\n%s\n' "$output" >&2
    exit 1
fi

echo "full-i64 invariant smoke OK: unconstrained endpoint was not truncated"
