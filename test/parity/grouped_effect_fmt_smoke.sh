#!/usr/bin/env bash
# Canonical grouped grants must agree byte-for-byte and remain stable on a second pass.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
if [ "${ELISA_GROUPED_FMT_REPORTER_PREBUILT:-0}" = 1 ]; then
    s0() { "$ELISA_GROUPED_FMT_STAGE0" "$@"; }
    s1() {
        local output="" input=""
        while [ "$#" -gt 0 ]; do
            case "$1" in
                -emit) shift 2 ;;
                -o) output="$2"; shift 2 ;;
                *) input="$1"; shift ;;
            esac
        done
        "$ELISA_GROUPED_FMT_REPORTER" < "$input" > "$output"
    }
else
    source "$REPO_ROOT/test/parity/resolve_elisac.sh"
    source "$REPO_ROOT/test/parity/emit_parity_lib.sh"
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fail() { echo "grouped_effect_fmt FAILED: $*"; exit 1; }
check() {
    local name="$1" expected="$2"
    cat > "$WORK/$name.elisa"
    s0 -emit fmt "$WORK/$name.elisa" > "$WORK/$name.s0" 2> "$WORK/$name.s0.err" || fail "$name stage0"
    s1 -emit fmt -o "$WORK/$name.s1" "$WORK/$name.elisa" > /dev/null 2> "$WORK/$name.s1.err" || fail "$name stage1"
    cmp -s "$WORK/$name.s0" "$WORK/$name.s1" || fail "$name byte parity"
    rg -Fq -- "$expected" "$WORK/$name.s1" || fail "$name exact grouped spelling"
    s1 -emit fmt -o "$WORK/$name.again" "$WORK/$name.s1" > /dev/null 2>&1 || fail "$name roundtrip"
    cmp -s "$WORK/$name.s1" "$WORK/$name.again" || fail "$name formatter stability"
}
check adjacent 'def f() -> i32 can[Global{Read,Write}]:' <<'CASE'
def f() -> i32 can[Global.Read, Global.Write]:
    can Global.Read, Global.Write:
        return 0
CASE
rg -Fxq '    return 0 can Global{Read,Write}' "$WORK/adjacent.s1" || fail 'adjacent postfix exact output'
check mixed 'can[Global{Read,Write}, Unsafe.PointerCast]' <<'CASE'
def f() -> i32 can[Global.Read, Global.Write, Unsafe.PointerCast]:
    return 0 can Global.Read, Global.Write, Unsafe.PointerCast
CASE
check interrupted 'can[Global{Read,Write}, Unsafe.PointerCast]' <<'CASE'
def f() -> i32 can[Global.Read, Unsafe.PointerCast, Global.Write]:
    return 0
CASE
check duplicate 'can[Global{Read,Read}]' <<'CASE'
def f() -> i32 can[Global.Read, Global.Read]:
    return 0
CASE
check whole_family 'can[Global{Read,Write}, Global]' <<'CASE'
def f() -> i32 can[Global.Read, Global, Global.Write]:
    return 0
CASE
check trusted 'trusted Global{Read,Write}:' <<'CASE'
def f() -> i32:
    trusted [Global.Read, Global.Write]:
        x = 1
        return x
CASE
check typed 'can[Writer[i32]{Read,Write}]' <<'CASE'
def f() -> i32 can[Writer[i32].Read, Writer[i32].Write]:
    return 0
CASE
check distinct_types 'can[Writer[i32].Read, Writer[i64].Write]' <<'CASE'
def f() -> i32 can[Writer[i32].Read, Writer[i64].Write]:
    return 0
CASE
check grouped_input 'can[Global{Read,Write,Read}]' <<'CASE'
def f() -> i32 can[Global{Read,Write}, Global.Read]:
    return 0
CASE
check alias_refs 'can[ReadAccess, WriteAccess, Global{Read,Write}]' <<'CASE'
def f() -> i32 can[ReadAccess, WriteAccess, Global.Read, Global.Write]:
    return 0
CASE
check via_ref 'can[Writer[sview] via Console.Write, Global{Read,Write}]' <<'CASE'
def f() -> i32 can[Writer[sview] via Console.Write, Global.Read, Global.Write]:
    return 0
CASE
check via_interrupt 'can[Global{Read,Write}, Writer[sview] via Console.Write]' <<'CASE'
def f() -> i32 can[Global.Read, Writer[sview] via Console.Write, Global.Write]:
    return 0
CASE
check typed_spacing 'can[Writer[i32]{Read,Write}]' <<'CASE'
def f() -> i32 can[Writer[ i32 ].Read, Writer[i32].Write]:
    return 0
CASE
check singleton 'can[Global.Read]' <<'CASE'
def f() -> i32 can[Global.Read]:
    return 0 can Global.Read
CASE
check grouped_type_input 'can[Writer[i32]{Read,Write,Read}]' <<'CASE'
def f() -> i32 can[Writer[i32]{Read,Write}, Writer[i32].Read]:
    return 0
CASE
check multiple_groups 'can[Global{Read,Write}, Unsafe{PointerCast,UncheckedIndex}]' <<'CASE'
def f() -> i32 can[Global.Read, Global.Write, Unsafe.PointerCast, Unsafe.UncheckedIndex]:
    return 0 can Global.Read, Global.Write, Unsafe.PointerCast, Unsafe.UncheckedIndex
CASE
check typed_block_spacing 'return 0 can Writer[i32]{Read,Write}' <<'CASE'
def f() -> i32:
    can Writer[ i32 ].Read, Writer[i32].Write:
        return 0
CASE
echo 'grouped_effect_fmt OK: 17 cases'
