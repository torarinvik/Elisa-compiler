#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/unsupported.c" \
    "$ROOT/test/repro/pymodule_unsupported_set.elisa" >"$WORK/c.log" 2>&1; then
    echo "unsupported set element unexpectedly compiled in pymodule-c mode" >&2
    exit 1
fi
grep -Fq 'set element type `Point` is not supported by Python interop' "$WORK/c.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/unsupported.json" \
    "$ROOT/test/repro/pymodule_unsupported_set.elisa" >"$WORK/manifest.log" 2>&1; then
    echo "unsupported set element unexpectedly compiled in pymodule manifest mode" >&2
    exit 1
fi
grep -Fq 'set element type `Point` is not supported by Python interop' "$WORK/manifest.log"

echo "pymodule unsupported set diagnostic OK"
