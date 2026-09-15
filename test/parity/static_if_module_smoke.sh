#!/usr/bin/env bash
# A module declared once per `static if` / `static elif` / `static else` branch is ONE
# module, not a redeclaration (stage0 walks only the active branch). A second declaration
# in the SAME (active) branch is still rejected identically by both compilers; stage0 walks
# only the active branch, so the duplicate lives under a condition true on POSIX hosts.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ROOT="$ROOT" python3 - "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import subprocess, sys
stage0, stage1, work = sys.argv[1:]
work = Path(work)
branches = ('module Outer:\n    public:\n        static if ELISA_TARGET_OS_LINUX:\n            module Inner:\n                public:\n                    const V: i64 = 1\n        static elif ELISA_TARGET_OS_WINDOWS:\n            module Inner:\n                public:\n                    const V: i64 = 3\n        static else:\n            module Inner:\n                public:\n                    const V: i64 = 2\n\ndef main() -> i64:\n    return 0\n')
same_branch = ('module Outer:\n    public:\n        static if ELISA_TARGET_OS_POSIX:\n            module Inner:\n                public:\n                    const V: i64 = 1\n            module Inner:\n                public:\n                    const W: i64 = 1\n\ndef main() -> i64:\n    return 0\n')
def compile(compiler, source):
    return subprocess.run([compiler, '-emit', 'obj', '-o', str(work/'out.o'), str(source)], capture_output=True, timeout=60)
src = work / 'branches.elisa'; src.write_text(branches)
results = [compile(c, src) for c in (stage0, stage1)]
assert all(r.returncode == 0 for r in results), [(r.returncode, r.stderr) for r in results]
print('static_if_module_branches: stage0/stage1 accepted PASS', flush=True)
src = work / 'same_branch.elisa'; src.write_text(same_branch)
results = [compile(c, src) for c in (stage0, stage1)]
assert all(r.returncode != 0 for r in results) and results[0].stderr == results[1].stderr, [(r.returncode, r.stderr) for r in results]
print('static_if_module_same_branch: stage0/stage1 byte-identical rejection PASS', flush=True)
# The RUNTIME fixture: three nested-const spellings, compiled and run by both compilers.
import os
root = Path(os.environ['ROOT'])
subprocess.run(['clang', '-c', str(root/'test/parity/profile_hooks.c'), '-o', str(work/'hooks.o')], check=True)
codes = []
for stage, compiler in enumerate((stage0, stage1)):
    obj, exe = work / f'nested{stage}.o', work / f'nested{stage}'
    r = subprocess.run([compiler, '-emit', 'obj', '-O0', '-o', str(obj), str(root/'test/differential/cases/nested_module_const.elisa')], capture_output=True, timeout=60)
    assert r.returncode == 0, (compiler, r.stderr)
    subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'hooks.o'), str(root/'build/runtime/elisacore_runtime.o')], check=True)
    codes.append(subprocess.run([str(exe)], timeout=90).returncode)
assert codes == [0, 0], codes
print('nested_module_const: stage0/stage1 runtime PASS', flush=True)
PY
