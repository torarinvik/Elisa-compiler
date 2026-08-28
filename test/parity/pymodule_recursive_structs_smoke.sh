#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-c \
    -o "$WORK/recursive.c" "$ROOT/test/repro/pymodule_recursive_structs.elisa" \
    >"$WORK/stdout" 2>"$WORK/stderr"; then
    echo "recursive struct unexpectedly accepted" >&2
    exit 1
fi

grep -q 'directly self-recursive' "$WORK/stderr"
echo "pymodule recursive structs diagnostic OK"
