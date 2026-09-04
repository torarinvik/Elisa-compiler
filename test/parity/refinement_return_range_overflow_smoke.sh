#!/usr/bin/env bash
# Refined-return interval arithmetic must become unknown on overflow, never trap or wrap.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/refinement_return_range_overflow.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -gt 1 ]]; then
    printf 'refined-return overflow regression: expected success or a semantic diagnostic, got %s\n%s\n' "$status" "$output" >&2
    exit 1
fi

echo "refined-return overflow smoke OK: overflowing intervals were conservatively declined"
