#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/unsupported.c" \
    "$ROOT/test/repro/pymodule_unsupported_struct_list.elisa" \
    >"$WORK/stdout" 2>"$WORK/stderr"; then
    echo "pymodule unsupported struct list smoke FAILED (C shim unexpectedly succeeded)" >&2
    exit 1
fi
grep -Fq 'cannot represent parameter `batch`' "$WORK/stderr"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/unsupported.json" \
    "$ROOT/test/repro/pymodule_unsupported_struct_list.elisa" \
    >"$WORK/manifest.out" 2>"$WORK/manifest.err"; then
    echo "pymodule unsupported struct list smoke FAILED (manifest unexpectedly succeeded)" >&2
    exit 1
fi
grep -Fq 'cannot represent parameter `batch`' "$WORK/manifest.err"

echo "pymodule unsupported struct list diagnostic OK"
