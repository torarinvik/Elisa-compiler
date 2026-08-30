#!/usr/bin/env bash
# `-emit c-archive` — the C ABI delivery bundle: `<base>.a` plus three audit sidecars
# (`.h`, `.unsafe.txt`, `.elisa-abi.json`).
#
# Both compilers run in the SAME working directory with the SAME relative output path,
# because the manifest records absolute paths — comparing runs from different directories
# reports a difference that is only the directory.
#
# Byte parity on all three sidecars AND identical archive MEMBER NAMES, plus an end-to-end
# check that a C program links against stage1's archive and runs. The member names matter:
# `ar` records a member by its BASENAME, so writing the temp object beside the archive as
# `<base>.elisacore_module.o` silently produced a differently-named member.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

differ=0
same=0

check_bundle() {
    local label="$1"; local body="$2"
    rm -rf "$WORK/s0" "$WORK/s1"; mkdir -p "$WORK/s0" "$WORK/s1"
    printf '%s' "$body" > "$WORK/s0/unit.elisa"
    printf '%s' "$body" > "$WORK/s1/unit.elisa"
    ( cd "$WORK/s0" && "$ELISACORE_BIN" -emit c-archive -o lib.a unit.elisa </dev/null >/dev/null 2>&1 ) || {
        echo "SKIP $label (stage0 declined)"; return; }
    ( cd "$WORK/s1" && bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit c-archive -o lib.a unit.elisa >/dev/null 2>&1 ) || {
        differ=$((differ + 1)); echo "FAILED $label: stage1 produced no bundle"; return; }
    local bad=0
    for ext in h unsafe.txt elisa-abi.json; do
        cmp -s "$WORK/s0/lib.$ext" "$WORK/s1/lib.$ext" || {
            bad=1; echo "DIFF $label lib.$ext:"; diff "$WORK/s0/lib.$ext" "$WORK/s1/lib.$ext" | head -6; }
    done
    local m0 m1
    m0="$(ar t "$WORK/s0/lib.a" | tr '\n' ' ')"
    m1="$(ar t "$WORK/s1/lib.a" | tr '\n' ' ')"
    [[ "$m0" == "$m1" ]] || { bad=1; echo "DIFF $label members: [$m0] vs [$m1]"; }
    if [[ "$bad" == 0 ]]; then same=$((same + 1)); else differ=$((differ + 1)); fi
}

check_bundle "library" 'def add2(a: i64, b: i64) -> i64:
    return a + b

export fn lib_add(a: i64, b: i64) -> i64 = add2
'
check_bundle "no exports" 'def helper() -> i64:
    return 1

def main() -> i64:
    return 0
'
check_bundle "struct export" 'struct Vec2:
    x: f64
    y: f64

def take(p: Vec2&) -> u32:
    return 0.u32()

export fn v_take(p: Vec2&) -> u32 = take
'

# END TO END: a C consumer must link stage1's archive and run.
rm -rf "$WORK/e2e"; mkdir -p "$WORK/e2e"
cat > "$WORK/e2e/unit.elisa" <<'EOF'
def add2(a: i64, b: i64) -> i64:
    return a + b

export fn lib_add(a: i64, b: i64) -> i64 = add2
EOF
( cd "$WORK/e2e" && bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit c-archive -o lib.a unit.elisa >/dev/null 2>&1 ) || {
    echo "END-TO-END: stage1 produced no bundle"; differ=$((differ + 1)); }
cat > "$WORK/e2e/use.c" <<'EOF'
#include "lib.h"
#include <stdio.h>
int main(void){ printf("%lld\n", (long long)lib_add(20, 22)); return 0; }
EOF
if ( cd "$WORK/e2e" && clang use.c lib.a -o use >/dev/null 2>&1 ); then
    out="$("$WORK/e2e/use" 2>&1)"
    if [[ "$out" == "42" ]]; then
        echo "END-TO-END: C consumer linked and printed 42"
    else
        echo "END-TO-END: wrong output: $out"; differ=$((differ + 1))
    fi
else
    echo "END-TO-END: C consumer did NOT link against stage1's archive"; differ=$((differ + 1))
fi

echo "emit_c_archive bundle: $same identical, $differ divergent"
[ "$differ" -eq 0 ] || { echo "emit_c_archive parity FAILED"; exit 1; }
echo "emit_c_archive parity OK"
