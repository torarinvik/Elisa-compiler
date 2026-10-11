#!/usr/bin/env bash
# Stage in test/parity. Exact candidate runtime, strict O0/O2 and retained reserve LLVM.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
COMPILER="${ELISA_STAGE1_BIN:?Pin fresh exact candidate Stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$COMPILER"
[[ -f "$RUNTIME" && -s "$RUNTIME.inputs.sha256" ]] || { echo "missing runtime or freshness stamp" >&2; exit 2; }
ELISA_RUNTIME_OBJ="$RUNTIME" bash "$ROOT/scripts/build_runtime_object.sh" --check
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
WORK="${ELISA_RESERVE_EVIDENCE_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/elisa-reserve-owner.XXXXXX")}"
mkdir -p "$WORK"
if [[ -z "${ELISA_RESERVE_EVIDENCE_DIR:-}" ]]; then
    trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fi
LINK_OBJECTS=("$RUNTIME")
for fixture in reserve_destination_arena_native; do
    for opt in 0 2; do
        ELISA_STAGE1_BIN="$COMPILER" bash "$ROOT/scripts/elisac_stage1.sh" -O"$opt" -emit obj \
            -o "$WORK/$fixture-O$opt.o" "$ROOT/test/parity/$fixture.elisa" \
            >"$WORK/$fixture-O$opt.log" 2>&1 || { cat "$WORK/$fixture-O$opt.log" >&2; exit 1; }
        "$CLANG" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS "$WORK/$fixture-O$opt.o" \
            "${LINK_OBJECTS[@]}" -L"$ELISA_LLVM_LIBDIR" $ELISA_LLVM_LIBS \
            -Wl,-rpath,"$ELISA_LLVM_LIBDIR" $ELISA_LD_STACK_512M -o "$WORK/$fixture-O$opt"
        "$WORK/$fixture-O$opt" >"$WORK/$fixture-O$opt.stdout" 2>&1
    done
done
ELISA_STAGE1_BIN="$COMPILER" bash "$ROOT/scripts/elisac_stage1.sh" -O0 -emit llvm \
    -o "$WORK/reserve_destination_arena.ll" "$ROOT/test/parity/reserve_destination_arena_native.elisa" \
    >"$WORK/reserve_destination_arena-llvm.log" 2>&1
python3 - "$WORK/reserve_destination_arena.ll" <<'PYCODE'
from pathlib import Path
import re, sys
ir = Path(sys.argv[1]).read_text()
def body(name):
    match = re.search(r"define[^\n]* @" + name + r"\([^\n]*\).*?\n}", ir, re.S)
    assert match, name
    return match.group(0)
def operands(text, kind):
    return re.findall(r"%reserve\." + kind + r"\w* = call ptr @arena_" + kind + r"\(ptr ([^,]+),", text)
main = body("main")
assert "%owner = alloca" in main, "destination owner declaration missing"
for kind in ("alloc", "realloc"):
    found = operands(main, kind)
    assert len(found) == 6 and all(x == "%owner" for x in found), (kind, found)
helper = body("reserve_from_inner")
parameters = re.findall(r"ptr (%[\w.]+)", helper.splitlines()[0])
assert len(parameters) == 4, parameters
for kind in ("alloc", "realloc"):
    found = operands(helper, kind)
    assert found == parameters[2:], (kind, found, parameters)
print("reserve arena operands OK: owner for locals/fields, caller arenas for refs")
PYCODE
echo "reserve destination ownership OK at O0/O2"
