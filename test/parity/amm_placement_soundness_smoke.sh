#!/usr/bin/env bash
# Automatic memory placement must never pick storage that dies before the value does.
# Each fixture reproduced a use-after-free in stage1's automation layer (memsafe audit
# 2026-09-26): the wrong placement gives a DIFFERENT exit code, not a crash, so the gate
# checks the value at -O0 and -O2 against stage0 (or a fixed answer where stage0 rejects).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
failures=0

# run COMPILER SOURCE OPT TAG -> prints the exit code, or "reject"
run() {
    local compiler="$1" source="$2" opt="$3" tag="$4" rc=0
    "$compiler" -emit obj "$opt" -o "$WORK/$tag.o" "$source" > "$WORK/$tag.log" 2>&1 || { echo reject; return; }
    clang -Wl,-dead_strip -o "$WORK/$tag" "$WORK/$tag.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
    "$WORK/$tag" > /dev/null 2>&1 || rc=$?
    echo "$rc"
}

check() {
    local name="$1" source="$2" expected="$3"
    for opt in -O0 -O2; do
        got="$(run "$STAGE1" "$source" "$opt" "$name$opt-1")"
        if [[ "$got" != "$expected" ]]; then
            echo "FAIL $name $opt: stage1 $got, expected $expected" >&2
            failures=$((failures + 1))
        else
            echo "$name $opt: $got PASS"
        fi
    done
}

for fixture in amm_optional_return_arena amm_stack_value_block_escape amm_address_of_growth_arena amm_drop_type_move \
        amm_generic_ref_growth amm_generic_two_arena_growth amm_generic_error_growth; do
    source="$ROOT/test/differential/cases/$fixture.elisa"
    oracle="$(run "$STAGE0" "$source" -O0 "$fixture-0")"
    [[ "$oracle" != reject ]] || { echo "FAIL $fixture: stage0 rejects the fixture" >&2; failures=$((failures + 1)); continue; }
    check "$fixture" "$source" "$oracle"
done
# stage0 rejects this one ("cannot infer region parameter"); 4 + 100*40 = 4004 = 164 mod 256.
check local_ref_growth_arena "$ROOT/test/fixtures/amm/local_ref_growth_arena.elisa" 164
# Growth and stores THROUGH a local alias of a parameter (stage0 rejects each; 160 = the UAF).
check ref_alias_growth "$ROOT/test/fixtures/amm/ref_alias_growth.elisa" 164
check ref_alias_forwarded_growth "$ROOT/test/fixtures/amm/ref_alias_forwarded_growth.elisa" 164
check ref_alias_chain "$ROOT/test/fixtures/amm/ref_alias_chain.elisa" 164
# inner[3] + outer[3] + 100*40 = 4 + 5 + 4000 = 4009 = 169 mod 256.
check ref_alias_two_regions "$ROOT/test/fixtures/amm/ref_alias_two_regions.elisa" 169
check index_store_escape "$ROOT/test/fixtures/amm/index_store_escape.elisa" 164
# A generic effect operation that grows the caller's darray (stage1-only feature).
check static_effect_growth "$ROOT/test/fixtures/amm/static_effect_growth.elisa" 164

# After `r <- q` the reference may point into either caller region: no single arena
# outlives both referents, so the function must decline LOUDLY rather than guess one.
ambiguous_source="$ROOT/test/fixtures/amm/ref_alias_rebind_ambiguous.elisa"
if "$STAGE1" -emit obj -o "$WORK/ambiguous.o" "$ambiguous_source" > "$WORK/ambiguous.log" 2>&1; then
    echo "FAIL ref_alias_rebind_ambiguous: stage1 guessed an arena instead of declining" >&2
    failures=$((failures + 1))
elif ! grep -q 'declined 1: fill@' "$WORK/ambiguous.log"; then
    echo "FAIL ref_alias_rebind_ambiguous: rejected for another reason:" >&2
    cat "$WORK/ambiguous.log" >&2
    failures=$((failures + 1))
else
    echo "ref_alias_rebind_ambiguous: decline PASS"
fi

drop_source="$ROOT/test/fixtures/amm/drop_type_implicit_copy.elisa"
if "$STAGE1" -emit obj -o "$WORK/drop.o" "$drop_source" > "$WORK/drop.log" 2>&1; then
    echo "FAIL drop_type_implicit_copy: stage1 accepted an implicit copy of a __drop__ type" >&2
    failures=$((failures + 1))
elif ! grep -q 'linear value "t" must be moved explicitly before move into local "u"' "$WORK/drop.log"; then
    echo "FAIL drop_type_implicit_copy: rejected for another reason:" >&2
    cat "$WORK/drop.log" >&2
    failures=$((failures + 1))
else
    echo "drop_type_implicit_copy: reject PASS"
fi

[[ "$failures" == 0 ]] || { echo "amm placement soundness: $failures failure(s)" >&2; exit 1; }
echo "amm placement soundness PASS"
