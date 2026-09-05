#!/usr/bin/env bash
# Semantic constant folding must decline source expressions outside i64, never trap or wrap.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/parity/fixtures/constant_fold_overflow.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

set +e
output="$("$WRAPPER" -emit obj -O0 -o "$WORK/program.o" "$SOURCE" 2>&1)"
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
    printf 'constant-fold overflow regression: expected a conservative successful compile, got %s\n%s\n' "$status" "$output" >&2
    exit 1
fi
if [[ "$output" == *"static assert failed"* ]]; then
    printf 'constant-fold overflow regression: overflowing expression was folded as an i64 fact\n%s\n' "$output" >&2
    exit 1
fi

echo "constant-fold overflow smoke OK: overflowing fold was conservatively declined"
