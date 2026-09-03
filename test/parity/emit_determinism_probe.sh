#!/usr/bin/env bash
# NOT a gate -- a reproducer for the one open nondeterminism bug. Slow (each run
# compiles the whole compiler) and expected to need several attempts, so it is
# never wired into the aggregate suite. Run it by hand when hunting this.
#
# WHAT IS KNOWN, measured 2026-09-03:
#
#   The stage1 compiler occasionally emits a DIFFERENT object for the same input.
#   Rate on the flattened compiler source: roughly 1 run in 8. The output takes
#   exactly one of two forms, 32 bytes apart, so it is a single binary decision
#   flipping, not drift.
#
#   The symbol COUNT is identical; __text differs by 52 bytes across 15 functions
#   with small +/- deltas (main, several Backend.*, Parser.*, Semantic.check_full,
#   frontend_parse, frontend_parser_parse_file). Disassembling one of them shows
#   the difference is in the PROLOGUE: parameters are stored to different slots in
#   a different order. Every affected function is one that threads a hidden AST
#   store or arena, which is where to look first.
#
#   This is what made the gen3 fixpoint flap. self_host_gen3_smoke now re-runs
#   both generations on failure and prints the four sizes, which is how the
#   unstable generation was identified: gen2 reproduced itself, gen3 did not.
#
# NOT yet ruled out: an address-dependent decision (ASLR), an uninitialized read,
# or a hash order somewhere in the store/arena parameter layout. name_hash is
# FNV-1a over the name's bytes and is NOT a candidate.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_DETERMINISM_BIN:-$ROOT/build/gen3_check/elisac-stage1-gen3}"
SRC="${ELISA_DETERMINISM_SRC:-$ROOT/build/gen3_check/flat.elisa}"
RUNS="${ELISA_DETERMINISM_RUNS:-10}"

[ -x "$BIN" ] || { echo "emit_determinism_probe SKIP: no compiler at $BIN"; echo "  run test/parity/self_host_gen3_smoke.sh first to build one"; exit 0; }
[ -f "$SRC" ] || { echo "emit_determinism_probe SKIP: no input at $SRC"; exit 0; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT INT TERM HUP
echo "emit_determinism_probe: $RUNS runs of $(basename "$BIN") over $(basename "$SRC")"

declare -a seen=()
for i in $(seq 1 "$RUNS"); do
    { printf '%s\n' "$WORK/out$i.o"; cat "$SRC"; } > "$WORK/req"
    "$BIN" < "$WORK/req" >/dev/null 2>&1
    sum="$(cksum < "$WORK/out$i.o" | awk '{print $1}')"
    bytes="$(wc -c < "$WORK/out$i.o" | tr -d ' ')"
    echo "  run $i: $bytes bytes, cksum $sum"
    seen+=("$sum")
done

distinct="$(printf '%s\n' "${seen[@]}" | sort -u | wc -l | tr -d ' ')"
if [ "$distinct" -eq 1 ]; then
    echo "emit_determinism_probe: all $RUNS runs identical (the bug did NOT reproduce this time)"
    exit 0
fi
echo "emit_determinism_probe: REPRODUCED -- $distinct distinct outputs across $RUNS runs."
echo "  Objects are in $WORK for the length of this run only; re-run with the directory"
echo "  kept if you need to diff them (per-function sizes via nm -n, then objdump)."
exit 1
