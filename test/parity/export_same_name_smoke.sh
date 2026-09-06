#!/usr/bin/env bash
# Same-name exports must be reachable from C under their own names, with the C
# ABI, from BOTH compilers: a scalar export is the implementation itself, an
# aggregate export is a wrapper (implementation renamed `.impl`), and a
# same-name type/global register nothing new. This is the executable counterpart
# to export_same_name_parity_smoke.sh.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -n "${ELISACORE_BIN:-}" ]]; then
    STAGE0="$ELISACORE_BIN"
else
    STAGE0=""
    for stage0_candidate in \
        "$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac" \
        "$ROOT/../../../Go projects/structpy-tree/compiler/bin/elisac" \
        "$ROOT/../wasm-sdk-stage0/compiler/bin/elisac"; do
        if [[ -x "$stage0_candidate" ]]; then
            STAGE0="$stage0_candidate"
            break
        fi
    done
    STAGE0="${STAGE0:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
fi
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
FIXTURE="$ROOT/test/repro/export_same_name.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-same-name.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "same-name export C smoke SKIP: no stage0 at $STAGE0"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "same-name export C smoke SKIP: no stage1 at $STAGE1"; exit 0; }
[[ -f "$RUNTIME" ]] || { echo "same-name export C smoke SKIP: no runtime object at $RUNTIME"; exit 0; }

cat > "$WORK/caller.c" <<'C'
#include <stdio.h>
#include "mod.h"
int main(void) {
    Vec2 v = { 20, 22 };
    int ok = 1;
    ok &= add(1, 2) == 3;
    ok &= vec2_sum(v) == 42;
    ok &= mul(6, 7) == 42;
    ok &= MAGIC == 1337;
    ok &= uses_internally() == 1344;
    Vec2 m = make_vec2(5, 6);
    ok &= m.x == 5 && m.y == 6;
    ok &= vec2_sum(make_vec2(8, 9)) == 17;
    printf("%s\n", ok ? "ALL OK" : "FAILED");
    return ok ? 0 : 1;
}
C

status=0
run_one() {
    local label="$1"
    shift
    local dir="$WORK/$label"
    mkdir -p "$dir"

    if ! "$@" -emit obj -O0 -o "$dir/mod.o" "$FIXTURE" >"$dir/obj.log" 2>&1; then
        echo "same-name export C smoke FAIL [$label]: compile"
        head -3 "$dir/obj.log"
        status=1
        return
    fi
    if ! "$@" -emit header -o "$dir/mod.h" "$FIXTURE" >"$dir/header.log" 2>&1; then
        echo "same-name export C smoke FAIL [$label]: header"
        head -3 "$dir/header.log"
        status=1
        return
    fi
    for symbol in _add _vec2_sum _mul _uses_internally _make_vec2; do
        nm "$dir/mod.o" | grep -q " T $symbol\$" || {
            echo "same-name export C smoke FAIL [$label]: $symbol is not external"
            nm "$dir/mod.o" | grep -i "$symbol" || true
            status=1
            return
        }
    done
    if ! clang -Wl,-dead_strip -I"$dir" -o "$dir/caller" "$WORK/caller.c" "$dir/mod.o" "$RUNTIME" >"$dir/link.log" 2>&1; then
        echo "same-name export C smoke FAIL [$label]: link"
        head -5 "$dir/link.log"
        status=1
        return
    fi
    if [[ "$("$dir/caller" || true)" != "ALL OK" ]]; then
        echo "same-name export C smoke FAIL [$label]: C caller failed"
        status=1
        return
    fi
    echo "same-name export C smoke OK [$label]: ALL OK from C"
}

run_one stage0 "$STAGE0"
run_one stage1 "$ROOT/scripts/elisac_stage1.sh"
exit "$status"
