#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/duplicate_struct.c" \
    "$ROOT/test/repro/pymodule_duplicate_struct_name.elisa" >"$WORK/out" 2>"$WORK/err"; then
    echo "duplicate module-local struct names should be rejected" >&2
    exit 1
fi
grep -Fq 'struct name `Point` appears more than once; Python interop currently requires unique named-struct names' "$WORK/err"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-pyi \
    -o "$WORK/duplicate_struct.pyi" \
    "$ROOT/test/repro/pymodule_duplicate_struct_name.elisa" >"$WORK/pyi.out" 2>"$WORK/pyi.err"; then
    echo "duplicate module-local struct names should be rejected for stubs" >&2
    exit 1
fi
grep -Fq 'struct name `Point` appears more than once; Python interop currently requires unique named-struct names' "$WORK/pyi.err"

echo "pymodule duplicate-struct diagnostic OK"
