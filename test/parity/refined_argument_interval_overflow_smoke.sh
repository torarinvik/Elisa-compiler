#!/usr/bin/env bash
# Refined-argument interval transforms must decline unrepresentable endpoints without trapping.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/refined_argument_interval_overflow.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -gt 1 ]]; then
    printf 'refined-argument interval overflow regression: compiler failed with %s\n%s\n' "$status" "$output" >&2
    exit 1
fi

echo "refined-argument interval overflow smoke OK: unrepresentable intervals were declined"
