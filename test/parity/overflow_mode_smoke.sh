#!/usr/bin/env bash
# Signed-overflow mode: `-foverflow=trap` (the DEFAULT) and `-foverflow=wrap`.
#
# `i64::MAX + 1`, computed from a runtime value so neither compiler can fold it, must:
#   - trap (SIGTRAP, exit 133) with no flag at -O0 AND -O2, and under an explicit
#     `-foverflow=trap` -- including when `ELISACORE_OVERFLOW=wrap` is inherited;
#   - wrap to i64::MIN under `-foverflow=wrap` or `ELISACORE_OVERFLOW=wrap`, at both levels,
#     with no `with.overflow` intrinsic and no `nsw` on the arithmetic in the IR (a `nsw`
#     would make the wrap poison, not defined behaviour).
# A misspelled mode is rejected, never silently read as either one.
#
# Parity with stage0, which has no flag but gates on the optimization level: stage0 -O0
# traps (== stage1's default) and stage0 -O2 wraps (== stage1 `-foverflow=wrap`). stage1
# deliberately keeps trapping at -O2 by default; wrap is an explicit opt-in.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac-stage0}"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
RUNTIME="$REPO_ROOT/build/runtime/elisacore_runtime.o"
[[ -x "$STAGE0" ]] || { echo "overflow smoke: no stage0 at $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "overflow smoke: no stage1 product at $STAGE1" >&2; exit 2; }
[[ -f "$RUNTIME" ]] || { echo "overflow smoke: no runtime object at $RUNTIME" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
unset ELISACORE_OVERFLOW
bash "$REPO_ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$WORK/hooks.c"

# 7 = wrapped to a negative value, 3 = no overflow at all (a wrong answer in every mode).
cat >"$WORK/add.elisa" <<'SRC'
extern atoi(text: cstr) -> i32

def bump(x: i64, by: i64) -> i64:
    return x + by

def main() -> i64:
    one: i64 = atoi("1").i64()
    top: i64 = 9223372036854775807
    result: i64 = bump(top, one)
    return 7 if result < 0 else 3
SRC

# $1 = label, $2 = want (trap|wrap), $3 = compiler, $4.. = flags (env via `env` prefix in $3)
run() {
    local label="$1" want="$2"; shift 2
    local exe="$WORK/$label"
    if ! "$@" -emit obj -o "$exe.o" "$WORK/add.elisa" >"$exe.log" 2>&1; then
        echo "overflow smoke FAILED: $label did not compile: $(head -n 1 "$exe.log")" >&2
        failed=$((failed + 1)); return
    fi
    if ! clang -Wl,-dead_strip -o "$exe" "$exe.o" "$WORK/hooks.c" "$RUNTIME" >>"$exe.log" 2>&1; then
        echo "overflow smoke FAILED: $label did not link" >&2
        failed=$((failed + 1)); return
    fi
    "$exe" >/dev/null 2>&1
    local status=$? expected=133
    [[ "$want" == wrap ]] && expected=7
    if [[ "$status" -ne "$expected" ]]; then
        echo "overflow smoke FAILED: $label exited $status, want $expected ($want)" >&2
        failed=$((failed + 1))
    fi
    local ll="$exe.ll"
    if ! "$@" -emit llvm -o "$ll" "$WORK/add.elisa" >/dev/null 2>&1; then
        echo "overflow smoke FAILED: $label: -emit llvm failed" >&2
        failed=$((failed + 1)); return
    fi
    if [[ "$want" == trap ]]; then
        # -O2 inlines `bump` and folds the intrinsic against the constant into a compare;
        # the trap call survives the pipeline, the intrinsic name does not.
        grep -Eq "llvm.sadd.with.overflow|llvm.trap" "$ll" || { echo "overflow smoke FAILED: $label: no overflow trap in IR" >&2; failed=$((failed + 1)); }
    else
        if grep -q "with.overflow" "$ll" || grep -Eq "= (add|sub|mul) nsw" "$ll"; then
            echo "overflow smoke FAILED: $label: wrap IR still checks or carries nsw" >&2
            failed=$((failed + 1))
        fi
    fi
}

for opt in -O0 -O2; do
    run "s1_default$opt" trap "$STAGE1" "$opt"
    run "s1_trap$opt" trap "$STAGE1" "$opt" -foverflow=trap
    run "s1_wrap$opt" wrap "$STAGE1" "$opt" -foverflow=wrap
    run "s1_envwrap$opt" wrap env ELISACORE_OVERFLOW=wrap "$STAGE1" "$opt"
    run "s1_envwrap_flagtrap$opt" trap env ELISACORE_OVERFLOW=wrap "$STAGE1" "$opt" -foverflow=trap
    run "s1_envjunk$opt" trap env ELISACORE_OVERFLOW=Wrap "$STAGE1" "$opt"
done
# The oracle's two behaviours, one per stage1 mode.
run s0_O0 trap "$STAGE0" -O0
run s0_O2 wrap "$STAGE0" -O2

if "$STAGE1" -foverflow=saturate -emit obj -o "$WORK/bad.o" "$WORK/add.elisa" >"$WORK/bad.log" 2>&1; then
    echo "overflow smoke FAILED: -foverflow=saturate was accepted" >&2
    failed=$((failed + 1))
elif ! grep -q "unknown flag: -foverflow=saturate" "$WORK/bad.log"; then
    echo "overflow smoke FAILED: -foverflow=saturate rejected for the wrong reason: $(head -n 1 "$WORK/bad.log")" >&2
    failed=$((failed + 1))
fi

if [[ "$failed" -ne 0 ]]; then
    echo "overflow smoke: $failed failure(s)" >&2
    exit 1
fi
echo "overflow smoke: ok (trap default at -O0/-O2, wrap opt-in, env mirror, stage0 parity)"
