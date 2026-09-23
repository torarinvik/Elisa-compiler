#!/usr/bin/env bash
# `view[T]` indexing traps and slices CLAMP -- at -O0 and -O2, in both compilers.
#
# Two stage1 memory-safety defects (memsafe audit S1a/S1b, 2026-09-22), measured against
# stage0 875d before the fix:
#   S1a  `v[i]` / `v[i] <- x` on a `view[T]` had NO bounds guard (the index watchdog covered
#        darray and fixed arrays only): `v[5]` on a 3-element view read 0 from past the
#        buffer, and the store corrupted the neighbouring heap word. stage0 traps (133).
#   S1b  `base[lo:hi]` computed `hi - lo` unclamped: `xs[2:1]` gave a view of 2^64-1
#        elements, `xs[1:10]` one past the darray's end. stage0 clamps every receiver with a
#        known length (darray, fixed array, view, sview; a cstr through strlen), so each
#        row below is its answer. A raw `u8&` has no length and is unclamped in both.
# The bounds come from a C call so neither compiler can fold them.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac-stage0}"
STAGE1="$REPO_ROOT/bin/elisac-stage1"
RUNTIME="$REPO_ROOT/build/runtime/elisacore_runtime.o"
[[ -x "$STAGE0" ]] || { echo "slice bounds smoke: no stage0 at $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "slice bounds smoke: no stage1 product at $STAGE1" >&2; exit 2; }
[[ -f "$RUNTIME" ]] || { echo "slice bounds smoke: no runtime object at $RUNTIME" >&2; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
failed=0
bash "$REPO_ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$WORK/hooks.c"

HEADER='extern atoi(text: cstr) -> i32

def arg(text: cstr) -> i64:
    return atoi(text).i64()
'
THREE='        xs: mutable darray[i64] = []
        xs.push(1)
        xs.push(2)
        xs.push(3)'

# $1 = shape, $2 = first bound, $3 = second bound (unused by the index shapes)
source_for() {
    printf '%s\n' "$HEADER"
    case "$1" in
    view_read)  printf 'def main() -> i64:\n    can Memory.Allocate, Abort.Panic:\n%s\n        v: view[i64] = xs[0:3]\n        return v[arg("%s").usize()]\n' "$THREE" "$2" ;;
    view_store) printf 'def main() -> i64:\n    can Memory.Allocate, Abort.Panic:\n%s\n        v: mutable view[i64] = xs[0:3]\n        v[arg("%s").usize()] <- 9\n        return xs[1]\n' "$THREE" "$2" ;;
    da_slice)   printf 'def main() -> i64:\n    can Memory.Allocate, Abort.Panic:\n%s\n        v: view[i64] = xs[arg("%s"):arg("%s")]\n        return v.len.i64()\n' "$THREE" "$2" "$3" ;;
    arr_slice)  printf 'def main() -> i64:\n    a: i64[4] = [1, 2, 3, 4]\n    v: view[i64] = a[arg("%s"):arg("%s")]\n    return v.len.i64()\n' "$2" "$3" ;;
    view_slice) printf 'def main() -> i64:\n    can Memory.Allocate, Abort.Panic:\n%s\n        v: view[i64] = xs[0:3]\n        w: view[i64] = v[arg("%s"):arg("%s")]\n        return w.len.i64()\n' "$THREE" "$2" "$3" ;;
    sv_slice)   printf 'def main() -> i64:\n    s: sview = "hello"\n    t: sview = s[arg("%s"):arg("%s")]\n    return t.len\n' "$2" "$3" ;;
    cs_slice)   printf 'def main() -> i64:\n    s: cstr = "hello"\n    t: sview = s[arg("%s"):arg("%s")]\n    return t.len\n' "$2" "$3" ;;
    esac
}

# shape a b want -- `want` is stage0 875d's exit code at -O0 and -O2 (133 = SIGTRAP).
CASES='view_read 1 - 2
view_read 5 - 133
view_read 3 - 133
view_store 1 - 9
view_store 3 - 133
da_slice 2 1 0
da_slice 1 10 2
da_slice 0 3 3
da_slice -1 2 0
da_slice 5 9 0
arr_slice 3 1 0
arr_slice 2 9 2
arr_slice 1 3 2
arr_slice 9 9 0
view_slice 2 1 0
view_slice 1 10 2
view_slice 1 2 1
sv_slice 3 1 0
sv_slice 1 -1 4
sv_slice -2 2 2
sv_slice 1 99 4
sv_slice 7 9 0
cs_slice 3 1 0
cs_slice 1 -1 4
cs_slice -2 2 2
cs_slice 1 99 4
cs_slice 7 9 0
cs_slice 1 3 2'

run_one() {   # $1 = label, $2 = compiler, $3 = opt, $4 = source, $5 = exe; prints exit code or BUILD
    "$2" -emit obj "$3" -o "$5.o" "$4" >"$5.log" 2>&1 || { echo "BUILD($(grep -a -m1 -i error "$5.log" | cut -c1-120))"; return; }
    clang -Wl,-dead_strip -o "$5" "$5.o" "$WORK/hooks.c" "$RUNTIME" >>"$5.log" 2>&1 || { echo LINK; return; }
    "$5" >/dev/null 2>&1
    echo $?
}

total=0
while read -r shape a b want; do
    name="${shape}_${a}_${b}"
    source_for "$shape" "$a" "$b" >"$WORK/$name.elisa"
    for opt in -O0 -O2; do
        for label in stage0 stage1; do
            compiler="$STAGE0"; [[ "$label" == stage1 ]] && compiler="$STAGE1"
            total=$((total + 1))
            got="$(run_one "$label" "$compiler" "$opt" "$WORK/$name.elisa" "$WORK/${name}_${label}${opt}" 2>/dev/null)"
            if [[ "$got" != "$want" ]]; then
                echo "slice bounds smoke FAILED: $label $opt $name: got $got, want $want" >&2
                failed=$((failed + 1))
            fi
        done
    done
done <<<"$CASES"

if [[ "$failed" -ne 0 ]]; then
    echo "slice bounds smoke FAILED: $failed of $total check(s)" >&2
    exit 1
fi
echo "slice bounds smoke OK: $total checks; view indexing traps and slices clamp under both compilers at -O0 and -O2" >&2
