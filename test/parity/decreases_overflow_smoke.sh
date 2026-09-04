#!/usr/bin/env bash
# An overflowing measure delta must not turn an increasing loop into a termination proof.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/decreases_overflow.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -ne 0 || "$output" != *'measure could not be proven to strictly decrease'* ]]; then
    printf 'decreases overflow regression: increasing loop was not reported, status %s\n%s\n' "$status" "$output" >&2
    exit 1
fi

echo "decreases overflow smoke OK: wrapped negative delta was not accepted"
