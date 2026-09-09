#!/usr/bin/env bash
# Index bounds checks are the DEFAULT, at every optimization level, in both compilers.
#
# A store one past a fixed array must trap (SIGTRAP via llvm.trap) rather than land
# on the next global -- with no flag, at -O0 and at -O2, from stage0 and from stage1.
# The in-bounds twin must run to completion, and the emitted IR must carry the guard
# at -O2. This is the gate for the 2026-09-09 finding: both compilers guarded only at
# -O0 (stage1 only under -fbounds-check), so a wrongly sized global was overwritten
# silently in an ordinary build.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac-stage0}"
STAGE1="$REPO_ROOT/bin/elisac-stage1"
RUNTIME="$REPO_ROOT/build/runtime/elisacore_runtime.o"
[[ -x "$STAGE0" ]] || { echo "bounds smoke: no stage0 at $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "bounds smoke: no stage1 product at $STAGE1" >&2; exit 2; }
[[ -f "$RUNTIME" ]] || { echo "bounds smoke: no runtime object at $RUNTIME" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
bash "$REPO_ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$WORK/hooks.c"

# The index is produced by a C call at runtime, so neither compiler can fold it;
# one source per index keeps the probe free of any optional-returning extern.
probe() {   # $1 = index
    cat <<SRC
extern atoi(text: cstr) -> i32

global mutable buf: u8[8] = zeroed
global mutable canary: u64 = 7

def main() -> i64:
    index: usize = atoi("$1").usize()
    buf[index] <- 1
    return 0 if canary == 7 else 9
SRC
}
probe 7 >"$WORK/inside.elisa"
probe 40 >"$WORK/outside.elisa"

build() {   # $1 = compiler, $2 = opt, $3 = source, $4 = exe; prints the first failure line
    "$1" -emit obj "$2" -o "$4.o" "$3" >"$4.log" 2>&1 || { head -n 1 "$4.log"; return 1; }
    clang -Wl,-dead_strip -o "$4" "$4.o" "$WORK/hooks.c" "$RUNTIME" >>"$4.log" 2>&1 || { grep -m1 -i error "$4.log"; return 1; }
}

check() {   # $1 = compiler label, $2 = compiler, $3 = opt level
    local label="$1" compiler="$2" opt="$3" reason
    if ! reason="$(build "$compiler" "$opt" "$WORK/inside.elisa" "$WORK/${label}_${opt}_inside")"; then
        echo "bounds smoke FAILED: $label $opt did not build: $reason" >&2
        failed=$((failed + 1)); return
    fi
    if ! reason="$(build "$compiler" "$opt" "$WORK/outside.elisa" "$WORK/${label}_${opt}_outside")"; then
        echo "bounds smoke FAILED: $label $opt did not build: $reason" >&2
        failed=$((failed + 1)); return
    fi
    "$WORK/${label}_${opt}_inside" >/dev/null 2>&1
    local in_status=$?
    "$WORK/${label}_${opt}_outside" >/dev/null 2>&1
    local out_status=$?
    if [[ "$in_status" -ne 0 ]]; then
        echo "bounds smoke FAILED: $label $opt: in-bounds store exited $in_status, want 0" >&2
        failed=$((failed + 1))
    fi
    # SIGTRAP is reported as 128+5 by the shell; llvm.trap is what both backends emit.
    if [[ "$out_status" -ne 133 ]]; then
        echo "bounds smoke FAILED: $label $opt: out-of-bounds store exited $out_status, want 133 (trap)" >&2
        failed=$((failed + 1))
    fi
    local ll="$WORK/${label}_${opt}.ll"
    # Block names ("wd.in_bounds") do not survive the -O2 pipeline; the trap call does.
    if ! "$compiler" -emit llvm "$opt" -o "$ll" "$WORK/outside.elisa" >/dev/null 2>&1 || ! grep -q "llvm.trap" "$ll"; then
        echo "bounds smoke FAILED: $label $opt: no index guard in the emitted IR" >&2
        failed=$((failed + 1))
    fi
}

for opt in -O0 -O2; do
    check stage0 "$STAGE0" "$opt"
    check stage1 "$STAGE1" "$opt"
done

if [[ "$failed" -ne 0 ]]; then
    echo "bounds smoke FAILED: $failed check(s)" >&2
    exit 1
fi
echo "bounds smoke OK: out-of-bounds stores trap at -O0 and -O2 under both compilers; in-bounds twins run" >&2
