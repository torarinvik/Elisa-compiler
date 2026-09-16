#!/usr/bin/env bash
# docs/127 D9 — a C enum's value set is open at the ABI, so `match` exhaustiveness over one is
# only sound for a value VALIDATED on the way in. Four things must agree between the compilers:
# the validated fixture RUNS clean at -O0 and -O2, the unchecked reinterpretation is refused
# with a byte-identical message, an `@open` enum cannot be covered by naming its members, and
# the validator rejects a value a RANGE check would have admitted (the sparse-member case).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
if [ ! -x "$STAGE0" ] || [ ! -x "$STAGE1" ]; then
    echo "extern_enum_smoke FAIL: stage0 ($STAGE0) or stage1 ($STAGE1) is unavailable" >&2
    exit 1
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
ROOT="$ROOT" python3 - "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import os, subprocess, sys
stage0, stage1, work = sys.argv[1:]
work = Path(work); root = Path(os.environ['ROOT'])
runtime = root / 'build/runtime/elisacore_runtime.o'
source = root / 'test/differential/cases/extern_enum.elisa'

def compile_errors(compiler, text, name):
    path = work / f'{name}.elisa'
    path.write_text(text)
    done = subprocess.run([compiler, '-emit', 'llvm', '-O0', '-o', os.devnull, str(path)],
                          capture_output=True, text=True, timeout=60)
    lines = [l.split(': ', 1)[1] for l in (done.stdout + done.stderr).splitlines()
             if ': ' in l and 'warning:' not in l]
    return done.returncode, lines

# 1. The validated fixture RUNS clean from both compilers, at -O0 and at -O2. The whole point
#    of D9 is that the answer stops depending on the optimizer.
for level in ('-O0', '-O2'):
    for stage, compiler in enumerate((stage0, stage1)):
        obj, exe = work / f'fx{stage}{level}.o', work / f'fx{stage}{level}'
        subprocess.run([compiler, '-emit', 'obj', level, '-o', str(obj), str(source)], check=True, timeout=120)
        subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'hooks.o'), str(runtime)], check=True)
        code = subprocess.run([str(exe)], timeout=90).returncode
        assert code == 0, f'stage{stage} {level} fixture exit {code}'
print('extern_enum: validated fixture runs clean in both, -O0 and -O2 PASS', flush=True)

# 2. The unchecked reinterpretation is refused, byte-identically, in both spellings.
UNCHECKED = '''extern enum DeviceState of i32:
    Off = 0
    Idle = 1

@callconv(c)
extern device_state(handle: i32) -> i32

def main() -> i64:
    s: DeviceState = device_state(7).DeviceState()
    return s.i32().i64()
'''
codes, messages = [], []
for stage, compiler in enumerate((stage0, stage1)):
    code, lines = compile_errors(compiler, UNCHECKED, f'unchecked{stage}')
    codes.append(code)
    messages.append(lines)
assert codes[0] != 0 and codes[1] != 0, f'both must reject the reinterpretation: {codes}'
expected = 'cannot reinterpret a C value as extern enum "DeviceState": it is not known to be one of its members; construct it through DeviceState.from_c(...) so out-of-range values are rejected'
for stage, lines in enumerate(messages):
    assert expected in lines, f'stage{stage} message: {lines}'
print('extern_enum: unchecked reinterpretation refused byte-identically PASS', flush=True)

# 3. An @open enum is not covered by naming every member — only a default arm closes it.
OPEN = '''@open
extern enum SdlEvent of u32:
    Quit = 256
    KeyDown = 768

def handle(e: SdlEvent) -> i64:
    match e:
        SdlEvent.Quit:
            return 1
        SdlEvent.KeyDown:
            return 2

def main() -> i64:
    return handle(SdlEvent.Quit)
'''
expected_open = 'non-exhaustive match over @open extern enum "SdlEvent"; a C value outside its member list is possible, so a final _ arm is required'
for stage, compiler in enumerate((stage0, stage1)):
    code, lines = compile_errors(compiler, OPEN, f'open{stage}')
    assert code != 0, f'stage{stage} accepted an @open match with no default arm'
    assert expected_open in lines, f'stage{stage} message: {lines}'
print('extern_enum: @open match requires a default arm in both PASS', flush=True)

# 4. The C storage type is required. Not defaulted: a silent guess on an ABI boundary is the
#    kind of thing D9 exists to stop, and a shared default is one more thing to keep in sync.
NO_STORAGE = '''extern enum Mode:
    Off = 0
    On = 1

def main() -> i64:
    m: Mode = try Mode.from_c(1) else Mode.Off
    return 0 if m == Mode.On
    return 1
'''
expected_storage = 'extern enum "Mode" must declare its C storage type; add `of i32` (or the width the header uses) so the ABI is explicit'
for stage, compiler in enumerate((stage0, stage1)):
    code, lines = compile_errors(compiler, NO_STORAGE, f'nostorage{stage}')
    assert code != 0, f'stage{stage} accepted an extern enum with no storage type'
    assert expected_storage in lines, f'stage{stage} message: {lines}'
print('extern_enum: storage type required, byte-identically PASS', flush=True)

# 5. The validator tests MEMBERSHIP, not a range: the fixture's sparse enum (3, 27, 65) must
#    reject 4. A range check would admit it, and the exhaustive match would then be a lie.
#    Proven by the fixture's own exit code above; assert the shape stayed sparse so a later
#    edit cannot quietly turn this into a dense enum that a range check would also satisfy.
text = source.read_text()
assert 'Space = 3' in text and 'Letter = 65' in text and 'strlen("abcd")' in text, \
    'the fixture must keep a SPARSE member list and probe a value inside its range'
print('extern_enum: membership test is sparse-safe PASS', flush=True)
PY
