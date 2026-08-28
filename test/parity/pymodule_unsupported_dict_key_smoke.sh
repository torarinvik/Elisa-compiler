#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c -o "$WORK/unsupported.c" \
    "$ROOT/test/repro/pymodule_unsupported_dict_key.elisa" >"$WORK/unsupported.log" 2>&1; then
    echo "pymodule unsupported dict key smoke FAILED (C shim unexpectedly succeeded)" >&2
    exit 1
fi

grep -Fq 'dictionary key type `Point` is not supported by Python interop' "$WORK/unsupported.log"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule -o "$WORK/unsupported.json" \
    "$ROOT/test/repro/pymodule_unsupported_dict_key.elisa" >"$WORK/manifest.log" 2>&1; then
    echo "pymodule unsupported dict key smoke FAILED (manifest unexpectedly succeeded)" >&2
    exit 1
fi

grep -Fq 'dictionary key type `Point` is not supported by Python interop' "$WORK/manifest.log"
echo "pymodule unsupported dict key diagnostic OK"
