#!/usr/bin/env bash
# docs/127 D8 — a native extern's `ensure` is CHECKED at the call boundary in both compilers.
# Four things must agree: the guard is emitted for an untrusted extern and NOT for a
# @trusted one, the bounded form reads the view's own length, a LYING library is stopped at
# the boundary at runtime with the same message and exit code, and the whole check is erased
# above -O0 ("debug verifies what release assumes").
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
if [ ! -x "$STAGE0" ] || [ ! -x "$STAGE1" ]; then
    echo "extern_ensure_smoke FAIL: stage0 ($STAGE0) or stage1 ($STAGE1) is unavailable" >&2
    exit 1
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
cat > "$WORK/lying.c" <<'C'
/* Its Elisa declaration promises 42. It does not deliver 42. */
long lying_answer(void) { return 41; }
C
clang -c "$WORK/lying.c" -o "$WORK/lying.o"
cat > "$WORK/lying.elisa" <<'ELISA'
@callconv(c)
extern lying_answer() -> i64 ensure result == 42

def main() -> i64:
    return lying_answer() - 41
ELISA
ROOT="$ROOT" python3 - "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import os, re, subprocess, sys
stage0, stage1, work = sys.argv[1:]
work = Path(work); root = Path(os.environ['ROOT'])
runtime = root / 'build/runtime/elisacore_runtime.o'
source = root / 'test/differential/cases/extern_ensure.elisa'

# 1. The guard is emitted once -- for the untrusted extern only -- and the declarations agree.
guards, declares = [], []
for stage, compiler in enumerate((stage0, stage1)):
    ll = work / f'ens{stage}.ll'
    subprocess.run([compiler, '-emit', 'llvm', '-O0', '-o', str(ll), str(source)], check=True, timeout=60)
    text = ll.read_text()
    guards.append(text.count('extern postcondition failed'))
    declares.append(sorted(re.findall(r'^declare [^\n]*@strn?len\([^\n]*', text, re.M)))
assert guards == [1, 1], f'one guard each (the @trusted extern gets none): {guards}'
assert declares[0] == declares[1], declares
assert 'declare i64 @strnlen(ptr, i64, i64)' in declares[0], declares[0]
print('extern_ensure: one guard each, @trusted exempt, declarations byte-identical PASS', flush=True)

# 2. The bounded fixture RUNS clean from both: a truthful library passes its own boundary.
for stage, compiler in enumerate((stage0, stage1)):
    obj, exe = work / f'ens{stage}.o', work / f'ens{stage}'
    subprocess.run([compiler, '-emit', 'obj', '-O0', '-o', str(obj), str(source)], check=True, timeout=60)
    subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'hooks.o'), str(runtime)], check=True)
    code = subprocess.run([str(exe)], timeout=90).returncode
    assert code == 0, f'stage{stage} bounded fixture exit {code}'
print('extern_ensure: bounded ensure over a view runs clean in both PASS', flush=True)

# 3. A LYING library is stopped at the boundary, identically.
lying = work / 'lying.elisa'
for stage, compiler in enumerate((stage0, stage1)):
    obj, exe = work / f'lie{stage}.o', work / f'lie{stage}'
    subprocess.run([compiler, '-emit', 'obj', '-O0', '-o', str(obj), str(lying)], check=True, timeout=60)
    subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'lying.o'), str(work/'hooks.o'), str(runtime)], check=True)
    done = subprocess.run([str(exe)], capture_output=True, text=True, timeout=90)
    assert done.returncode != 0, f'stage{stage} accepted a lying extern (exit 0)'
    message = done.stdout + done.stderr
    assert 'extern postcondition failed' in message, f'stage{stage} said: {message!r}'
    assert ':2:44:' in message, f'stage{stage} reported the wrong position (expected the ==): {message!r}'
print('extern_ensure: a lying library is stopped at the boundary in both PASS', flush=True)

# 4. Erased above -O0 in both: the check is a checked-build guarantee, not a release cost.
for stage, compiler in enumerate((stage0, stage1)):
    ll = work / f'opt{stage}.ll'
    subprocess.run([compiler, '-emit', 'llvm', '-O2', '-o', str(ll), str(lying)], check=True, timeout=60)
    text = ll.read_text()
    assert 'extern postcondition failed' not in text, f'stage{stage} still checks at -O2'
print('extern_ensure: erased above -O0 in both PASS', flush=True)
PY
