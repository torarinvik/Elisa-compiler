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
for fixture in memory_speed_helper_reuse memory_speed_capacity memory_speed_stack memory_speed_fallbacks memory_speed_stack_budget memory_speed_stack_bounds memory_speed_helper_fallback memory_speed_helper_module memory_speed_generic_collision; do
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" == 0 ]] || compiler="$STAGE1"
        "$compiler" -emit obj -O2 -o "$WORK/$fixture-$stage.o" "$ROOT/test/differential/cases/$fixture.elisa"
        clang -Wl,-dead_strip -o "$WORK/$fixture-$stage" "$WORK/$fixture-$stage.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
        python3 - "$WORK/$fixture-$stage" "$WORK/output$stage" <<'PY'
import subprocess,sys
p=subprocess.run([sys.argv[1]],capture_output=True,timeout=90)
assert p.returncode==0,(sys.argv[1],p.returncode,p.stdout,p.stderr)
open(sys.argv[2],'wb').write(p.stdout+b'\nSTDERR\n'+p.stderr)
PY
    done
    cmp "$WORK/output0" "$WORK/output1"
    "$STAGE1" -emit llvm -O0 -o "$WORK/$fixture.ll" "$ROOT/test/differential/cases/$fixture.elisa"
    echo "$fixture: stage0/stage1 runtime PASS"
done
python3 - "$WORK" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
helper=(p/'memory_speed_helper_reuse.ll').read_text()
main=next(s for s in helper.split('\ndefine ') if '@main(' in s.split('\n')[0])
assert '__memory_helper_scratch' in main
assert 'call i64 @measure(' not in main
assert 'call void @arena_reset(' in main
assert 'memory.reserve.count' in (p/'memory_speed_capacity.ll').read_text()
assert 'memory.stack.buffer' in (p/'memory_speed_stack.ll').read_text()
fallback=(p/'memory_speed_fallbacks.ll').read_text()
assert 'memory.stack.buffer' not in fallback
assert 'memory.reserve.count' not in fallback
budget=(p/'memory_speed_stack_budget.ll').read_text()
assert sum('alloca' in s and 'memory.stack.buffer' in s for s in budget.splitlines())==1
bounds=(p/'memory_speed_stack_bounds.ll').read_text()
over=next(s for s in bounds.split('\ndefine ') if '@over_limit(' in s.split('\n')[0])
assert 'memory.stack.buffer' not in over
assert 'reserve.alloc' in over
assert '__memory_helper_scratch' not in (p/'memory_speed_helper_fallback.ll').read_text()
assert '__memory_helper_scratch' not in (p/'memory_speed_generic_collision.ll').read_text()
assert '__memory_helper_scratch' in (p/'memory_speed_helper_module.ll').read_text()
print('memory speed positive, fallback and stack budget IR PASS')
PY
ELISA_DISABLE_MEMORY_SPEED=1 "$STAGE1" -emit llvm -O0 -o "$WORK/disabled.ll" "$ROOT/test/differential/cases/memory_speed_helper_reuse.elisa"
if rg -q '__memory_helper_scratch|memory.stack.buffer|memory.reserve.count' "$WORK/disabled.ll"; then
    echo 'memory-speed ablation did not restore the baseline' >&2
    exit 1
fi
