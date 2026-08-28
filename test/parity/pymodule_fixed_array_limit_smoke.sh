#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if [[ ! -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ]]; then
    echo "pymodule fixed-array-limit smoke SKIP (stage1 unavailable)"
    exit 0
fi

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/input.json" "$ROOT/test/repro/pymodule_fixed_array_limit.elisa" \
    >"$WORK/input.out" 2>&1; then
    echo "oversized fixed-array parameter unexpectedly accepted by manifest" >&2
    exit 1
fi
grep -Fq 'cannot represent fixed-array parameter `values`' "$WORK/input.out"
grep -Fq 'at most 4096 elements' "$WORK/input.out"

if bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule \
    -o "$WORK/return.json" "$ROOT/test/repro/pymodule_fixed_array_return_limit.elisa" \
    >"$WORK/return.out" 2>&1; then
    echo "oversized fixed-array return unexpectedly accepted by manifest" >&2
    exit 1
fi
grep -Fq 'cannot represent a fixed-array return' "$WORK/return.out"
grep -Fq 'at most 4096 elements' "$WORK/return.out"

echo "pymodule fixed-array-limit diagnostics OK"
