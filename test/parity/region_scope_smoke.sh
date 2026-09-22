#!/usr/bin/env bash
# Manual region declarations bind a region for following statements; backing
# strategies and explicit @region annotations parse without fabricating blocks.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "region-scope smoke FAIL: $1" >&2; exit 1; }
clean() {
    local out
    out="$(printf '%s' "$1" | "$RPT")"
    grep -q '^P 0$' <<< "$out" || fail "parse error: $out"
    grep -q '^D 0$' <<< "$out" || fail "semantic diagnostic: $out"
}

clean $'def f(seed: i32) -> i32:\n    region scratch(1024)\n    value: i32& @scratch = new[scratch] seed + 1\n    result: i32 = value[0]\n    destroy scratch\n    return result\n'
# A line containing `new[r]` does not make the line's declared binding region-owned when the
# allocation is consumed as a call argument and the call returns a scalar.
clean $'def read(value: i64&) -> i64:\n    return value\n\ndef f() -> i64 can[Memory.Allocate, Abort.Panic]:\n    region r(1024):\n        result: i64 = read(new[r] 7)\n        return result\n'
out=$(printf '%s' $'def identity(value: i64&) -> i64&:\n    return value\n\ndef bad() -> i64&:\n    region r(1024):\n        return identity(new[r] 7)\n' | "$RPT")
grep -q 'cannot return reference: region dependency facts include local region "r"' <<< "$out" || fail "reference-returning call did not retain new[r] lifetime dependency: $out"
out=$(printf '%s' $'def identity(value: i64&) -> i64&:\n    return value\n\ndef bad() -> i64&:\n    region r(1024):\n        result: i64& = identity(new[r] 7)\n        return result\n' | "$RPT")
grep -q 'cannot return reference: region dependency facts include local region "r"' <<< "$out" || fail "reference-returning binding did not retain new[r] lifetime dependency: $out"
clean $'def f() -> void:\n    region a(1024) using reserve_commit\n    region b(1024) using fixed\n    region c(1024) using chained\n    region d(1024) using scratch\n    destroy a\n    destroy b\n    destroy c\n    destroy d\n'
out=$(printf 'def f() -> void:\n    region a(1024) using bogus\n    destroy a\n' | "$RPT")
grep -q 'unknown region backing "bogus"' <<< "$out" || fail "unknown backing strategy was not flagged: $out"
clean $'def id[T, @r](value: T& @r) -> T& @r:\n    return value\n'

out=$(printf 'def f() -> void:\n    value: i32&? @missing = null\n' | "$RPT")
grep -q 'unknown region qualifier "missing"' <<< "$out" || fail "unknown local region qualifier was not flagged: $out"

out=$(printf 'def f() -> void:\n    region left(64)\n    region right(64)\n    value: i32& @left = new[left] 1\n    other: i32& @right = value\n' | "$RPT")
grep -q 'variable "other" expects i32& @right, got i32& @left' <<< "$out" || fail "mismatched local regions were not flagged: $out"
clean $'def f() -> void:\n    region same(64)\n    value: i32& @same = new[same] 1\n    alias: i32& @same = value\n'

out=$(printf 'def bad() -> i32&:\n    region scratch(64)\n    value: i32& = new[scratch] 1\n    return value\n' | "$RPT")
grep -q 'cannot return reference: region dependency facts include local region "scratch"' <<< "$out" || fail "local-region return escape was not flagged: $out"
out=$(printf 'def bad() -> i32&:\n    region scratch(64)\n    value: i32& = new[scratch] 1\n    return value.cast[i32&]\n' | "$RPT")
grep -q 'cannot return reference: region dependency facts include local region "scratch"' <<< "$out" || fail "cast local-region return escape was not flagged: $out"
clean $'def id[T, @r](value: T& @r) -> T& @r:\n    alias: T& @r = value\n    return alias\n'

out="$(printf '%s' $'def f() -> void:\n    destroy missing\n' | "$RPT")"
grep -q "undefined identifier \"missing\"" <<< "$out" || fail "destroy of unknown region was not resolved: $out"

# A `@r` on a type with no region of its own, checked against stage0 line for line. stage0
# rejects it in resolveType with one of two sentences -- a fixed array is a builtin that
# "cannot carry a region", a scalar or declared struct/enum/alias is a named value that does not
# "carry an independent region" -- and then drops the region, so the value depends on nothing
# and a later `destroy` does not invalidate it. A generic parameter `T @r` resolves on another
# path and is accepted outright.
#
# stage1 once gave every one of these the named-value sentence, reported the rejected region
# again as a destroy-then-use or `cannot return reference` error, rejected `T @r`, and said
# nothing about a fixed array as a return type or in a struct that declares region params.
WORK_ROOT="$REPO_ROOT/build/region-scope-smoke"
mkdir -p "$WORK_ROOT"
WORK="$(mktemp -d "$WORK_ROOT/case.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
CARRY='applies to containers, references, and region-parameterized types;'
NAMED='is only valid on a function return type; named values do not carry an independent region'
carrierless=0
while IFS='|' read -r name body want; do
    printf '%b\n' "$body" > "$WORK/$name.elisa"
    want="${want//\$CARRY/$CARRY}"
    want="${want//\$NAMED/$NAMED}"
    want="$(printf '%s' "${want//@@/$'\n'}" | sort)"
    # stage0 exits 1 exactly when it rejects. On success `-emit semantic` prints its semantic
    # dump, whose lines carry the same `PATH:LINE:` prefix, so only a rejection is read.
    s0_rc=0
    s0_out="$("$ELISACORE_BIN" -emit semantic "$WORK/$name.elisa" 2>&1)" || s0_rc=$?
    s0=""
    [ "$s0_rc" -eq 0 ] || s0="$(grep -F "$WORK/$name.elisa:" <<< "$s0_out" | sed -E 's#^.*\.elisa:([0-9]+):[^ ]* #\1 #' | sort || true)"
    s1="$("$RPT" < "$WORK/$name.elisa" | sed -nE 's/^  L([0-9]+) /\1 /p' | sort || true)"
    [ "$s0" = "$want" ] || fail "$name: stage0 (the ORACLE) disagrees with the case:"$'\n'"$s0"$'\n'"expected:"$'\n'"$want"
    [ "$s1" = "$s0" ] || fail "$name: stage1 disagrees with stage0:"$'\n'"stage1:"$'\n'"$s1"$'\n'"stage0:"$'\n'"$s0"
    carrierless=$((carrierless + 1))
done <<'EOF'
local_array|def f() -> i64:\n    region r(64)\n    xs: array[i64, 4] @r = zeroed\n    destroy r\n    return xs[0]|3 region annotation `@r` $CARRY array[i64, 4] cannot carry a region
local_array_unspaced|def f() -> i64:\n    region r(64)\n    xs: array[i64,4] @r = zeroed\n    destroy r\n    return 0|3 region annotation `@r` $CARRY array[i64, 4] cannot carry a region
local_array_const_length|const N: i64 = 4\n\ndef f() -> i64:\n    region r(64)\n    xs: array[i64, N] @r = zeroed\n    destroy r\n    return 0|5 region annotation `@r` $CARRY array[i64, N] cannot carry a region
local_array_nested|def f() -> i64:\n    region r(64)\n    xs: array[array[i64, 2], 3] @r = zeroed\n    destroy r\n    return 0|3 region annotation `@r` $CARRY array[array[i64, 2], 3] cannot carry a region
local_array_mutable|def f() -> i64:\n    region r(64)\n    xs: mutable array[u8, 16] @r = zeroed\n    destroy r\n    return 0|3 region annotation `@r` $CARRY array[u8, 16] cannot carry a region
local_array_unknown_region|def f() -> i64:\n    xs: array[i64, 4] @r = zeroed\n    return 0|2 region annotation `@r` $CARRY array[i64, 4] cannot carry a region
param_array|def f(xs: array[i64, 4] @r) -> i64:\n    return 0|1 region annotation `@r` $CARRY array[i64, 4] cannot carry a region
return_array|def f[@r]() -> array[i64, 4] @r:\n    return zeroed|1 region annotation `@r` $CARRY array[i64, 4] cannot carry a region
field_array|struct Q:\n    xs: array[i64, 4] @r\n\ndef main() -> i64:\n    return 0|2 region annotation `@r` $CARRY array[i64, 4] cannot carry a region
field_array_region_params|struct Q[@r]:\n    xs: array[i64, 4] @r\n\ndef main() -> i64:\n    return 0|2 region annotation `@r` $CARRY array[i64, 4] cannot carry a region
field_struct_region_params|struct P:\n    a: i64\n\nstruct Q[@r]:\n    p: P @r\n\ndef main() -> i64:\n    return 0|5 region annotation `@r` $NAMED
field_scalar|struct Q[@r]:\n    x: i64 @r\n\ndef main() -> i64:\n    return 0|2 region annotation `@r` $NAMED
local_scalar_returned|def f() -> i64:\n    region r(64)\n    x: i64 @r = 1\n    destroy r\n    return x|3 region annotation `@r` $NAMED
local_struct_used|struct P:\n    a: i64\n\ndef f() -> i64:\n    region r(64)\n    p: P @r = P{a: 1}\n    destroy r\n    return p.a|6 region annotation `@r` $NAMED
local_enum|enum E:\n    A\n    B\n\ndef f() -> i64:\n    region r(64)\n    e: E @r = E.A\n    destroy r\n    return 0|7 region annotation `@r` $NAMED
local_alias|type Id = i64\n\ndef f() -> i64:\n    region r(64)\n    id: Id @r = 1\n    destroy r\n    return 0|5 region annotation `@r` $NAMED
local_unknown_type|def f() -> i64:\n    region r(64)\n    b: Nope @r = zeroed\n    destroy r\n    return 0|3 unknown type "Nope"
local_generic_parameter|def f[T, @r](x: T) -> T:\n    region s(64)\n    y: T @s = x\n    destroy s\n    return y|
param_generic_parameter|def f[T, @r](x: T @r) -> i64:\n    return 0|
field_generic_parameter|struct Box[T, @r]:\n    value: T @r\n\ndef main() -> i64:\n    return 0|
darray_still_depends|def f() -> i64:\n    region r(64)\n    xs: darray[i64] @r = [1]\n    destroy r\n    return xs[0]|5 value "xs" cannot be used: region dependency facts were invalidated by destroy of region "r"
EOF
[ "$carrierless" -eq 21 ] || fail "ran $carrierless of 21 carrier-less annotation cases"

echo "region-scope smoke OK: declarations/strategies/@regions bind; destroy consumes a resolved region; $carrierless carrier-less annotations match stage0"
