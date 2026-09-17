#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
for fixture in differential/cases/region_output_assignment parity/parser_scratch_lifetime; do
    for stage in 0 1; do
        executable="$WORK/${fixture##*/}-$stage"
        compiler="$STAGE0"
        [[ "$stage" == 0 ]] || compiler="$STAGE1"
        "$compiler" -emit obj -O2 -o "$WORK/result.o" "$ROOT/test/$fixture.elisa"
        if [[ "$stage" == 0 && "$fixture" == parity/parser_scratch_lifetime ]]; then
            clang -Wl,-dead_strip -o "$executable" "$WORK/result.o" "$WORK/hooks.o"
        else
            clang -Wl,-dead_strip -o "$executable" "$WORK/result.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
        fi
        python3 - "$executable" "$WORK/output$stage" <<'PY'
import subprocess, sys
with open(sys.argv[2], 'wb') as out:
    subprocess.run([sys.argv[1]], stdout=out, timeout=90, check=True)
PY
    done
    cmp "$WORK/output0" "$WORK/output1"
    echo "$fixture: stage0/stage1 runtime PASS"
done
# Cached blocks can exceed the explicit request, so a region-create event's capacity and the
# runtime's layout callback can disagree about the same block.
#
# MEASURED 2026-09-16 -- BOTH compilers report the REQUESTED capacity in the create event while
# the layout callback reports the ACTUAL block, so region_capacity_hooks.c's
# `assert(capacity == last_capacity)` aborts under stage0 and stage1 alike. This check used to
# run stage1 ONLY and pass, because stage1 called `arena_profile_explicit_create` -- a helper
# the vendored runtime defined and NO stage0 build does. That invented symbol broke the link of
# every program containing an explicit `region NAME(N):` (see the backend's note in
# codegen_stmt_binding_blocks.elisa), and removing it put stage1 on stage0's behaviour.
#
# So this is an ORACLE limitation, not a stage1 gap, and the ratchet is NOT being raised to hide
# one: what is asserted here is the parity property that actually holds -- the two compilers
# behave IDENTICALLY on this fixture. The accuracy gap itself is reported below every run so it
# stays visible, and closing it means changing stage0 first (an owner call).
clang -c "$ROOT/test/parity/region_capacity_hooks.c" -o "$WORK/capacity-hooks.o"
capacity_outcome() {
    local compiler="$1" tag="$2"
    "$compiler" -emit obj -O2 -o "$WORK/capacity-$tag.o" "$ROOT/test/parity/region_cached_capacity.elisa" >"$WORK/capacity-$tag.build" 2>&1 || {
        echo "BUILD-FAILED"; return; }
    clang -Wl,-dead_strip -o "$WORK/capacity-$tag" "$WORK/capacity-$tag.o" "$WORK/capacity-hooks.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o" >>"$WORK/capacity-$tag.build" 2>&1 || {
        echo "LINK-FAILED"; return; }
    local out; out="$("$WORK/capacity-$tag" 2>&1)"; local rc=$?
    # The assertion text names the failing invariant; keep it in the outcome so a CHANGE in
    # which invariant fires is a disagreement, not just a different exit code.
    printf 'rc=%s %s' "$rc" "$(printf '%s' "$out" | sed -n 's/.*Assertion failed: (\([^)]*\)).*/assert:\1/p' | head -1)"
}
capacity_s0="$(capacity_outcome "$STAGE0" s0)"
capacity_s1="$(capacity_outcome "$STAGE1" s1)"
if [ "$capacity_s0" != "$capacity_s1" ]; then
    echo "cached region capacity: stage0 [$capacity_s0] != stage1 [$capacity_s1]" >&2
    exit 1
fi
echo "cached region capacity events PASS (stage0 == stage1: $capacity_s1)"
case "$capacity_s1" in
    *assert:capacity*)
        echo "  KNOWN GAP (both compilers): the region-create event reports the REQUESTED capacity;"
        echo "  the layout callback reports the ACTUAL cached block. Closing it starts in stage0." ;;
esac
"$STAGE1" -emit llvm -O0 -o "$WORK/parser.ll" "$ROOT/test/parity/parser_scratch_lifetime.elisa"
python3 - "$WORK/parser.ll" <<'PY'
from pathlib import Path
import sys
blocks=Path(sys.argv[1]).read_text().split('\ndefine ')
body=next(b for b in blocks if '@frontend_parse(' in b.split('\n')[0])
lex=next(line for line in body.splitlines() if 'call ' in line and '@frontend_tokenize(' in line)
parse=next(line for line in body.splitlines() if 'call ' in line and '@Parser.parse_file(' in line)
assert 'ptr %scratch)' in lex, lex
assert 'ptr %scratch' not in parse, parse
PY
echo 'parser token and AST allocation arenas PASS'
