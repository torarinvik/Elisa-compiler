#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/unsupported.c" \
    "$ROOT/test/repro/pymodule_unsupported_nested_darray.elisa" >"$WORK/unsupported.log" 2>&1; then
    echo "deeper top-level nested darray should be rejected by pymodule-c" >&2
    exit 1
fi
grep -Fq 'supports nested darrays up to eight levels' "$WORK/unsupported.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/unsupported.json" \
    "$ROOT/test/repro/pymodule_unsupported_nested_darray.elisa" >"$WORK/manifest.log" 2>&1; then
    echo "deeper top-level nested darray should be rejected by the pymodule manifest" >&2
    exit 1
fi
grep -Fq 'supports nested darrays up to eight levels' "$WORK/manifest.log"
echo "pymodule unsupported nested darray diagnostic OK"
