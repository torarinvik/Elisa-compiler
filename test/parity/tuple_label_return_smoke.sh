#!/usr/bin/env bash
# Tuple labels may differ across a positional return when element types are identical.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
SOURCE="$REPO_ROOT/test/repro/tuple_label_return_probe.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$WRAPPER" -emit exe -O0 -o "$WORK/program" "$SOURCE"
set +e
"$WORK/program"
status=$?
set -e

if [[ "$status" -ne 42 ]]; then
    printf 'tuple-label return regression: expected 42, got %s\n' "$status" >&2
    exit 1
fi

echo "tuple-label return smoke OK: structurally compatible tuple returned 42"
