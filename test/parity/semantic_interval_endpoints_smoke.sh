#!/usr/bin/env bash
# Endpoint constraints must stay full-width and proof analyses must not wrap arithmetic.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/semantic_interval_endpoints.elisa"

output="$("$WRAPPER" -emit interpret "$SOURCE" 2>&1)"
contradictions="$(printf '%s\n' "$output" | grep -c 'preconditions of .* are contradictory' || true)"
unproven="$(printf '%s\n' "$output" | grep -c 'precondition of .* could not be proven' || true)"
preservation="$(printf '%s\n' "$output" | grep -c 'invariant is established on entry but could not be proven preserved' || true)"
refinement="$(printf '%s\n' "$output" | grep -c 'refinement argument' || true)"

if [[ "$contradictions" -ne 2 || "$unproven" -ne 2 || "$preservation" -ne 0 || "$refinement" -ne 0 ]]; then
    printf 'semantic interval endpoint regression: contradictions=%s unproven=%s preservation=%s refinement=%s\n%s\n' "$contradictions" "$unproven" "$preservation" "$refinement" "$output" >&2
    exit 1
fi

echo "semantic interval endpoint smoke OK: full-width and overflow cases classified safely"
