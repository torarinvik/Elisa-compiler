#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Early exits from value blocks and labelled loops (docs/119 E5 as relaxed; STYLE_GUIDE.md §5).
#
# test/fixtures/early_exit_pairs/NAME_block.elisa uses the new form — a `break`/`continue` inside
# a value block, a `'label:` loop expression left with `break 'label`, `continue 'label` from a
# value block in an inner loop — and NAME_stmt.elisa is the same program in statement form. For
# every pair:
#
#   - stage1 builds both files and both programs exit 0;
#   - stage1 compiles the two files to IDENTICAL machine code at -O0 and at -O2: the block form
#     costs nothing.
#
# stage1 only: stage0 rejects every jump out of a value block and has no loop labels.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
PAIRS="$ROOT/test/fixtures/early_exit_pairs"
fail() { printf 'early exit codegen smoke FAILED: %s\n' "$1" >&2; exit 1; }
command -v objdump >/dev/null 2>&1 || { echo "early exit codegen smoke: objdump is required" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-early-exit.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

# The disassembly without the file name line, which names the object.
disassemble() { objdump -d --no-show-raw-insn "$1" | sed -n '/^Disassembly/,$p'; }

pairs=0
for block in "$PAIRS"/*_block.elisa; do
    name="$(basename "$block" _block.elisa)"
    stmt="$PAIRS/${name}_stmt.elisa"
    [[ -f "$stmt" ]] || fail "$name has no _stmt twin"
    for source in "$block" "$stmt"; do
        base="$(basename "$source" .elisa)"
        bash "$WRAPPER" -emit exe -o "$WORK/$base.s1" "$source" >"$WORK/$base.log" 2>&1 || fail "stage1 failed to build $base: $(cat "$WORK/$base.log")"
        "$WORK/$base.s1" || fail "$base exited $?"
    done
    for level in -O0 -O2; do
        bash "$WRAPPER" "$level" -emit obj -o "$WORK/block.o" "$block" >"$WORK/obj.log" 2>&1 || fail "stage1 $level obj of ${name}_block: $(cat "$WORK/obj.log")"
        bash "$WRAPPER" "$level" -emit obj -o "$WORK/stmt.o" "$stmt" >"$WORK/obj.log" 2>&1 || fail "stage1 $level obj of ${name}_stmt: $(cat "$WORK/obj.log")"
        disassemble "$WORK/block.o" >"$WORK/block.s"
        disassemble "$WORK/stmt.o" >"$WORK/stmt.s"
        cmp -s "$WORK/block.s" "$WORK/stmt.s" || fail "$name $level: the block form's machine code differs from the statement form's:
$(diff "$WORK/block.s" "$WORK/stmt.s" | head -30)"
    done
    pairs=$((pairs + 1))
done
[[ "$pairs" -ge 4 ]] || fail "expected at least 4 pairs, found $pairs"
echo "early exit codegen smoke OK: $pairs pairs, identical machine code at -O0 and -O2"
