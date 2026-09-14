#!/usr/bin/env bash
# Run the forms, not just their parser: scope, value inference, update, and cleanup.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
python3 - "$ROOT" "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import subprocess, sys
root, stage0, stage1, work = sys.argv[1:]
work = Path(work)
for fixture in ('block_expression_scope', 'block_expression_cleanup', 'block_expression_values', 'block_expression_drop', 'block_expression_tuple'):
    outputs = []
    for stage, compiler in enumerate((stage0, stage1)):
        for level in ('-O0', '-O2'):
            artifact = f'{fixture}-stage{stage}-{level[1:]}'
            obj, exe = work / (artifact + '.o'), work / artifact
            source = Path(root) / 'test/differential/cases' / (fixture + '.elisa')
            subprocess.run([compiler, '-emit', 'obj', level, '-o', str(obj), str(source)], check=True, timeout=60)
            subprocess.run(['clang', '-Wl,-dead_strip', '-o', str(exe), str(obj), str(work/'hooks.o'), str(Path(root)/'build/runtime/elisacore_runtime.o')], check=True)
            result = subprocess.run([str(exe)], capture_output=True, timeout=90)
            assert result.returncode == 0, (fixture, compiler, level, result.returncode, result.stdout, result.stderr)
            outputs.append((result.stdout, result.stderr))
    assert all(output == outputs[0] for output in outputs), (fixture, outputs)
    print(f'{fixture}: stage0/stage1 O0/O2 runtime and byte parity PASS', flush=True)
# Keep lexical boundaries and capture checking enforced while widening valid forms.
for name, body in {
    'leaked_local': '    value: i64 =\n        hidden: i64 = 42\n        hidden\n    return hidden\n',
    'uncaptured_mutation': '    outer: mutable i64 = 0\n    value: i64 =\n        outer <- 42\n        outer\n    return value\n',
    'immutable_capture': '    outer: i64 = 1\n    value: i64 = |outer|\n        outer <- 42\n        outer\n    return value\n',
}.items():
    source = work / (name + '.elisa')
    source.write_text('def main() -> i64:\n' + body)
    for compiler in (stage0, stage1):
        result = subprocess.run([compiler, '-emit', 'obj', '-o', str(work/'invalid.o'), str(source)], capture_output=True, timeout=60)
        assert result.returncode == 1, (name, compiler, result.returncode, result.stderr)
    print(f'{name}: stage0/stage1 rejection PASS', flush=True)
PY
