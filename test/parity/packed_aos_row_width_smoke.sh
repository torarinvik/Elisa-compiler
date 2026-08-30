#!/usr/bin/env bash
# The AST AoS row must be as WIDE in stage1 as it is in stage0.
#
# The row is `{i32 tag, [N x i32] payload}` and N is the maximum, over every leaf of the
# `Node` hierarchy, of `ceil(payload_bytes / 4)`. stage0 computes it (ensurePackedEnumRowType
# + enumVariantPayloadSlots); stage1 had `32` written in — the value that maximum happened to
# have when the code was written.
#
# It silently stopped being the maximum the day an AST variant grew. Widening the position
# payload from a bare `line: u32` to a 24-byte `Pos` span took `Decl.Func` to 144 bytes, so
# every constructor wrote 16 bytes past its record and into the NEXT node's tag. There is no
# fault at the write and no decline: it surfaced as an exhaustive `match` falling through to
# its unreachable arm, thousands of nodes later, and ONLY in gen2 — the compiler stage1
# builds — because gen1 is built by stage0 and stage0 got the width right.
#
# Nothing in the gate could see it. `self_host_gen3_smoke` caught the CRASH, but only after
# a full bootstrap, and it names a symptom rather than the layout. This check compares the
# two compilers' emitted row types directly, on the same source, so a future widening fails
# here — in seconds, with the two numbers side by side — instead of as a trap in gen2.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
EC="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"

[ -x "$BIN" ] || { echo "packed_aos_row_width_smoke SKIP: no stage1 binary at $BIN"; exit 0; }
[ -x "$EC" ]  || { echo "packed_aos_row_width_smoke SKIP: no elisac at $EC"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# The compiler's own semantic layer: it includes the whole AST and constructs from every
# refinement, so both compilers lay out the full `Node` hierarchy for it.
SRC="$ROOT/src/semantic/semantic.elisa"

row_width() { # <compiler> <out.ll>
    "$1" -emit llvm "$SRC" -o "$2" >/dev/null 2>&1 || return 1
    grep -oE '\{ i32, \[[0-9]+ x i32\] \}' "$2" | head -1 | grep -oE '[0-9]+ x' | grep -oE '[0-9]+'
}

w0="$(row_width "$EC" "$WORK/stage0.ll")"
w1="$(row_width "$BIN" "$WORK/stage1.ll")"

if [ -z "$w0" ]; then
    echo "packed_aos_row_width_smoke FAILED: stage0 emitted no AoS row type for $SRC"
    exit 1
fi
if [ -z "$w1" ]; then
    echo "packed_aos_row_width_smoke FAILED: stage1 emitted no AoS row type for $SRC"
    exit 1
fi
if [ "$w0" != "$w1" ]; then
    echo "packed_aos_row_width_smoke FAILED: AST row payload is [$w1 x i32] in stage1 but [$w0 x i32] in stage0."
    echo "  A row NARROWER than stage0's overruns the record and corrupts the next node's tag —"
    echo "  silently. Size it from the widest variant (packed_ast_row_slots), do not re-baseline."
    exit 1
fi

echo "packed_aos_row_width_smoke OK: AST row payload [$w1 x i32] in both compilers"
