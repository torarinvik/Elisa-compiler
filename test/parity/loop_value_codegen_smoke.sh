#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Loop values bound to a local (docs/119 §3; src/backend/codegen_loop_value_binding.elisa).
#
# test/fixtures/loop_value_pairs/NAME_scoped.elisa writes an accumulator loop as a value
# (`sum: usize =` NEWLINE `for … |sum: usize = 0| -> sum:`); NAME_mutable.elisa is the same
# program with a `mutable` local and a statement loop. For every pair:
#
#   - both compilers build both files and every program exits 0 (zero-iteration, break and
#     tuple-yield cases included);
#   - stage1 compiles the two files to IDENTICAL machine code at -O0 and at -O2. This is the
#     promise behind the -Wnever-leak accumulator rewrite: scoping an accumulator costs nothing.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
PAIRS="$ROOT/test/fixtures/loop_value_pairs"
fail() { printf 'loop value codegen smoke FAILED: %s\n' "$1" >&2; exit 1; }
[[ -x "$STAGE0" ]] || { echo "loop value codegen smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v objdump >/dev/null 2>&1 || { echo "loop value codegen smoke: objdump is required" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-loop-value.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

# The disassembly without the file name line, which names the object.
disassemble() { objdump -d --no-show-raw-insn "$1" | sed -n '/^Disassembly/,$p'; }

pairs=0
for scoped in "$PAIRS"/*_scoped.elisa; do
    name="$(basename "$scoped" _scoped.elisa)"
    mutable="$PAIRS/${name}_mutable.elisa"
    [[ -f "$mutable" ]] || fail "$name has no _mutable twin"
    for source in "$scoped" "$mutable"; do
        base="$(basename "$source" .elisa)"
        bash "$WRAPPER" -emit exe -o "$WORK/$base.s1" "$source" >"$WORK/$base.log" 2>&1 || fail "stage1 failed to build $base: $(cat "$WORK/$base.log")"
        "$WORK/$base.s1" || fail "$base (stage1) exited $?"
        "$STAGE0" -emit c-archive -O2 -o "$WORK/$base.a" "$source" >"$WORK/$base.log" 2>&1 || fail "stage0 failed to build $base: $(cat "$WORK/$base.log")"
        clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/$base.s0" "$WORK/$base.a" >"$WORK/$base.log" 2>&1 || fail "could not link stage0 $base: $(cat "$WORK/$base.log")"
        "$WORK/$base.s0" || fail "$base (stage0) exited $?"
    done
    for level in -O0 -O2; do
        bash "$WRAPPER" "$level" -emit obj -o "$WORK/scoped.o" "$scoped" >"$WORK/obj.log" 2>&1 || fail "stage1 $level obj of ${name}_scoped: $(cat "$WORK/obj.log")"
        bash "$WRAPPER" "$level" -emit obj -o "$WORK/mutable.o" "$mutable" >"$WORK/obj.log" 2>&1 || fail "stage1 $level obj of ${name}_mutable: $(cat "$WORK/obj.log")"
        disassemble "$WORK/scoped.o" >"$WORK/scoped.s"
        disassemble "$WORK/mutable.o" >"$WORK/mutable.s"
        cmp -s "$WORK/scoped.s" "$WORK/mutable.s" || fail "$name $level: the scoped form's machine code differs from the mutable form's:
$(diff "$WORK/scoped.s" "$WORK/mutable.s" | head -30)"
    done
    pairs=$((pairs + 1))
done
[[ "$pairs" -ge 4 ]] || fail "expected at least 4 pairs, found $pairs"
echo "loop value codegen smoke OK: $pairs pairs run on both compilers, identical machine code at -O0 and -O2"
