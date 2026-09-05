#!/usr/bin/env bash
# Proof-hole affine normalization must decline overflow and retain both proof-hole reports.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/assert_proof_hole_overflow.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
    printf 'assert proof-hole overflow regression: hints must not fail compilation, got %s\n%s\n' "$status" "$output" >&2
    exit 1
fi
count="$(printf '%s\n' "$output" | grep -c 'proof hole: assertion could not be proven' || true)"
if [[ "$count" -lt 2 ]]; then
    printf 'assert proof-hole overflow regression: expected two proof holes, got %s\n%s\n' "$count" "$output" >&2
    exit 1
fi

echo "assert proof-hole overflow smoke OK: overflowing affine goals stayed unproven"
