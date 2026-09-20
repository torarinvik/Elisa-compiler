#!/usr/bin/env bash
# Unmodelled caller facts suppress approximate call-precondition diagnostics, and the
# early skip must preserve that behavior while avoiding the unused per-function fact setup.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/semantic_call_precondition_unclean_skip.elisa"

output="$("$WRAPPER" -emit interpret "$SOURCE" 2>&1)"
unproven="$(printf '%s\n' "$output" | grep -c 'could not be proven statically at this call' || true)"

if [[ "$unproven" -ne 1 ]]; then
    printf 'unclean caller skip regression: expected only the clean caller warning, got %s\n%s\n' "$unproven" "$output" >&2
    exit 1
fi

echo "unclean caller skip smoke OK: only modelable caller facts produced a warning"
