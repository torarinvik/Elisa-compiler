#!/usr/bin/env bash
# `-emit ir` must accept the common callable-extern subset and preserve it when stage0
# reads the resulting bundle. The writer is intentionally conservative for richer extern
# signatures because stage1's compact extern side table does not retain those shapes yet.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/const_enum_extern_param.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "ir writer SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "ir writer SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit ir -o "$WORK/stage0.elisair" "$SOURCE" >/dev/null
ELISA_STAGE1_BIN="$STAGE1" ELISA_ALLOW_STALE_STAGE1=1 \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit ir -o "$WORK/stage1.elisair" "$SOURCE" >/dev/null

# The stage0 lowered printer is the semantic oracle for the serialized AST. It compares
# the complete declaration/body tree, not merely whether both compilers accepted the file.
"$STAGE0" -emit lowered "$SOURCE" >"$WORK/source.lowered"
"$STAGE0" -emit lowered "$WORK/stage0.elisair" >"$WORK/stage0.lowered"
"$STAGE0" -emit lowered "$WORK/stage1.elisair" >"$WORK/stage1.lowered"
cmp -s "$WORK/source.lowered" "$WORK/stage0.lowered"
cmp -s "$WORK/source.lowered" "$WORK/stage1.lowered"

# Keep the negative boundary explicit: an optional return shape is not silently discarded
# while the stage1 AST remains compact. The command must decline by name rather than emit
# a weaker extern signature. Decorators themselves are encoded losslessly in the bundle.
NEGATIVE="$WORK/decorated.elisa"
printf '%s\n' '@link_name(probe_write)' 'extern probe_write(fd: i32) -> i32?' >"$NEGATIVE"
if ELISA_STAGE1_BIN="$STAGE1" ELISA_ALLOW_STALE_STAGE1=1 \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit ir -o "$WORK/negative.elisair" "$NEGATIVE" >/dev/null 2>"$WORK/negative.err"; then
    echo "ir writer FAILED: optional extern shape was emitted without its type information" >&2
    exit 1
fi
grep -q 'opaque extern signature shape' "$WORK/negative.err"

echo "ir writer smoke OK: callable extern round-trips; lossy optional shape declines"
