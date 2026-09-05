#!/usr/bin/env bash
# Local semantic evaluators must decline overflow rather than trapping or wrapping a fact.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/local_constant_evaluator_overflow.elisa"

set +e
output="$("$WRAPPER" -emit interpret "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -gt 1 ]]; then
    printf 'local constant evaluator overflow regression: compiler failed with %s\n%s\n' "$status" "$output" >&2
    exit 1
fi
if ! printf '%s\n' "$output" | grep -q 'could not be proven'; then
    printf 'local constant evaluator overflow regression: overflow was not kept unresolved\n%s\n' "$output" >&2
    exit 1
fi

echo "local constant evaluator overflow smoke OK: overflowing facts were declined"
