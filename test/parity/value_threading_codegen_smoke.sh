#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Value-threading, "owned in, owned out" (STYLE_GUIDE.md section 6;
# src/parser/ast_value_threading*.elisa, src/backend/codegen_value_threading*.elisa).
#
# test/fixtures/value_threading_pairs/NAME_value.elisa threads an owned value through a call
# (`arr <- push_one(arr, 4)` with `def push_one(arr: darray[i64], x: i64) -> darray[i64]`);
# NAME_ref.elisa is the same program in the `&` form (`push_one(&arr, 4)` with
# `arr: mutable darray[i64]&`), line for line. For every pair:
#
#   - stage1 builds both files and both programs exit 0;
#   - stage0 builds and runs the `&` form, as the oracle for the expected exit. stage0 has no
#     value-threading (it rejects the write to an immutable parameter), so the value forms are
#     stage1-only. The builtin pairs on dicts and `remove_at` include the stage1 runtime
#     (elisacore_std/elisacore_runtime.elisa), which stage0 rejects, so those are stage1-only
#     entirely; the smoke names them;
#   - stage1 compiles the two files to IDENTICAL machine code at -O0 and at -O2. This is the
#     promise behind the form: the values are only threaded through, never copied.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
PAIRS="$ROOT/test/fixtures/value_threading_pairs"
fail() { printf 'value threading codegen smoke FAILED: %s\n' "$1" >&2; exit 1; }
[[ -x "$STAGE0" ]] || { echo "value threading codegen smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v objdump >/dev/null 2>&1 || { echo "value threading codegen smoke: objdump is required" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-value-threading.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

# The disassembly without the file name line, which names the object.
disassemble() { objdump -d --no-show-raw-insn "$1" | sed -n '/^Disassembly/,$p'; }

pairs=0
stage1_only=""
for value in "$PAIRS"/*_value.elisa; do
    name="$(basename "$value" _value.elisa)"
    ref="$PAIRS/${name}_ref.elisa"
    [[ -f "$ref" ]] || fail "$name has no _ref twin"
    for source in "$value" "$ref"; do
        base="$(basename "$source" .elisa)"
        bash "$WRAPPER" -emit exe -o "$WORK/$base.s1" "$source" >"$WORK/$base.log" 2>&1 || fail "stage1 failed to build $base: $(cat "$WORK/$base.log")"
        "$WORK/$base.s1" || fail "$base (stage1) exited $?"
    done
    base="$(basename "$ref" .elisa)"
    if grep -q '^include .*elisacore_runtime.elisa' "$ref"; then
        stage1_only="$stage1_only $name"
    else
        "$STAGE0" -emit c-archive -O2 -o "$WORK/$base.a" "$ref" >"$WORK/$base.log" 2>&1 || fail "stage0 failed to build $base: $(cat "$WORK/$base.log")"
        clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/$base.s0" "$WORK/$base.a" >"$WORK/$base.log" 2>&1 || fail "could not link stage0 $base: $(cat "$WORK/$base.log")"
        "$WORK/$base.s0" || fail "$base (stage0) exited $?"
    fi
    for level in -O0 -O2; do
        bash "$WRAPPER" "$level" -emit obj -o "$WORK/value.o" "$value" >"$WORK/obj.log" 2>&1 || fail "stage1 $level obj of ${name}_value: $(cat "$WORK/obj.log")"
        bash "$WRAPPER" "$level" -emit obj -o "$WORK/ref.o" "$ref" >"$WORK/obj.log" 2>&1 || fail "stage1 $level obj of ${name}_ref: $(cat "$WORK/obj.log")"
        disassemble "$WORK/value.o" >"$WORK/value.s"
        disassemble "$WORK/ref.o" >"$WORK/ref.s"
        cmp -s "$WORK/value.s" "$WORK/ref.s" || fail "$name $level: the value form's machine code differs from the & form's:
$(diff "$WORK/value.s" "$WORK/ref.s" | head -30)"
    done
    pairs=$((pairs + 1))
done
[[ "$pairs" -ge 13 ]] || fail "expected at least 13 pairs, found $pairs"
echo "value threading codegen smoke OK: $pairs pairs, identical machine code at -O0 and -O2 (stage0 runs the & forms except the stage1-only:$stage1_only)"
