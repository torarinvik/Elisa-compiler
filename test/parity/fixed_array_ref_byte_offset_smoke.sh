#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$ROOT/test/repro/fixed_array_ref_byte_offset.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-fixed-array-ref.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"

[[ -x "$STAGE0" ]] || { echo "fixed array ref byte offset SKIP: no stage0 at $STAGE0" >&2; exit 0; }
[[ -x "$STAGE1" ]] || { echo "fixed array ref byte offset SKIP: no stage1 at $STAGE1" >&2; exit 0; }

"$STAGE0" -emit llvm -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for ir in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$ir" || {
        echo "fixed array ref byte offset FAIL: declined body in $ir" >&2
        exit 1
    }
    rg -q 'getelementptr \[64 x i8\], ptr .*i[0-9]+ 0, i[0-9]+ %' "$ir" || {
        echo "fixed array ref byte offset FAIL: array GEP does not use [0, offset] in $ir" >&2
        rg -n 'getelementptr|read_u32' "$ir" >&2
        exit 1
    }
done

echo "fixed array ref byte offset OK: stage0 and stage1 index fixed-array references by element offset"
