#!/usr/bin/env bash
# Strict fixed-index reasoning must reject arithmetic it cannot represent and empty slices.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/fixed_index_overflow.elisa"

output="$("$WRAPPER" -emit interpret "$SOURCE" 2>&1)"
count="$(printf '%s\n' "$output" | grep -c 'unchecked index requires')"

if [[ "$count" -ne 2 ]]; then
    printf 'fixed-index overflow regression: expected 2 strict diagnostics, got %s\n%s\n' "$count" "$output" >&2
    exit 1
fi

echo "fixed-index overflow smoke OK: overflow and zero extent were rejected"
