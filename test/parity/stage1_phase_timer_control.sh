#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-phase-timer.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
python3 - "$ROOT" "$WORK" <<'PYTHON'
from pathlib import Path
import sys
repo, work = map(Path, sys.argv[1:])
source = (repo / 'src/semantic/stage1_timings.elisa').read_text()
source = source.replace('@link_name("clock_gettime")', '@link_name("elisa_test_clock_gettime")')
tail = """
def main() -> i64:
    can Global{Read,Write}, Memory.Allocate, Abort.Panic:
        PhaseTimer::start()
        PhaseTimer::minor("first-minor")
        PhaseTimer::minor("second-minor")
        PhaseTimer::mark("whole-phase")
        PhaseTimer::mark("next-phase")
    return 0
"""
(work / 'fixture.elisa').write_text('include "' + str(repo / 'elisacore_std/elisacore_runtime.elisa') + '"\n' + source + tail)
PYTHON
cat >"$WORK/clock.c" <<'C'
#include <stdint.h>
struct timer_spec { int64_t seconds, nanos; };
int elisa_test_clock_gettime(int clock, void *out) {
    static int64_t wall, cpu;
    int64_t *counter = (clock == 1 || clock == 6) ? &wall : &cpu;
    struct timer_spec *spec = out;
    spec->seconds = 0;
    spec->nanos = (++*counter) * 1000000;
    return 0;
}
C
for level in O0 O2; do
    "$STAGE1" -emit obj "-$level" -o "$WORK/fixture.o" "$WORK/fixture.elisa"
    "${ELISA_CLANG:-clang}" "$WORK/fixture.o" "$WORK/clock.c" "$RUNTIME" -lm -o "$WORK/control"
    for mode in off 1 2; do
        if [[ "$mode" == off ]]; then
            env -u ELISA_STAGE1_TIMINGS "$WORK/control" 2>"$WORK/run.log"
        else
            ELISA_STAGE1_TIMINGS="$mode" "$WORK/control" 2>"$WORK/run.log"
        fi
        python3 - "$WORK/run.log" "$mode" <<'PYTHON'
import re, sys
rows = re.findall(r"stage1-timing: (.+) wall_ms=([0-9.]+) cpu_ms=([0-9.]+)", open(sys.argv[1]).read())
mode = sys.argv[2]
expected = []
if mode != 'off':
    expected = [('first-minor', '1.0', '1.0'), ('second-minor', '1.0', '1.0')] if mode == '2' else [('(short passes, each <20ms)', '2.0', '2.0')]
    expected += [('whole-phase', '5.0', '5.0'), ('next-phase', '1.0', '1.0')]
assert rows == expected, (rows, expected)
PYTHON
    done
done
echo "phase timer control OK at O0/O2: independent major/minor clocks and disabled mode"
