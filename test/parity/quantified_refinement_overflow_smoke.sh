#!/usr/bin/env bash
# Bounded quantifier evaluation must become unknown when a term overflows the host i64.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/quantified_refinement_overflow.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -ne 0 || "$output" != *'quantified refinement "NoOverflowWitness"'* ]]; then
    printf 'quantified-refinement overflow regression: expected a non-fatal unknown result, got %s\n%s\n' "$status" "$output" >&2
    exit 1
fi

echo "quantified-refinement overflow smoke OK: overflowing term was reported unknown"
