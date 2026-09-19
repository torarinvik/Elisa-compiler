#!/usr/bin/env bash
# Run the forms, not just their parser: scope, value inference, update, and cleanup.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
python3 - "$ROOT" "$STAGE0" "$STAGE1" "$WORK" <<'PY'
from pathlib import Path
import re, subprocess, sys
root, stage0, stage1, work = sys.argv[1:]
work = Path(work)
for fixture in ('block_optional_guard_match', 'block_expression_scope', 'block_expression_cleanup', 'block_expression_values', 'block_expression_drop', 'block_expression_tuple', 'tuple_function_tail', 'block_reference_threading', 'block_state_threading', 'with_collection_append'):
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
    if fixture == 'tuple_function_tail':
        for stage, compiler in enumerate((stage0, stage1)):
            bodies = []
            for spelling in ('n, n + 1', 'return n, n + 1'):
                probe = work / 'tuple_codegen.elisa'
                probe.write_text('def pair(n: i64) -> (first: i64, second: i64):\n    ' + spelling + '\n\ndef total(n: i64) -> i64:\n    a, b = pair(n)\n    a + b\n\nexport fn total(n: i64) -> i64 = total\n')
                ir = work / f'tuple-codegen-{stage}.ll'
                subprocess.run([compiler, '-emit', 'llvm', '-O2', '-o', str(ir), str(probe)], check=True, timeout=60)
                bodies.append(ir.read_text())
            assert bodies[0] == bodies[1], (compiler, 'tuple tail changes generated LLVM compared with explicit return')
            probe.write_text('def pair(n: i64) -> (first: i64, second: i64):\n    n, n + 1\n\ndef total(n: i64) -> i64:\n    a, b = pair(n)\n    a + b\n\nexport fn total(n: i64) -> i64 = total\n')
            subprocess.run([compiler, '-emit', 'llvm', '-O2', '-o', str(ir), str(probe)], check=True, timeout=60)
            total = re.search(r'define[^\n]*@total\([^\n]*\)[^{]*\{(.*?)\n\}', ir.read_text(), re.S)
            assert total, (compiler, 'missing total() in LLVM')
            assert 'alloca ' not in total.group(1), (compiler, total.group(1))
            calls = re.findall(r'\bcall\b[^\n]*@([^ (]+)', total.group(1))
            assert all(name in ('pair', 'llvm.sadd.with.overflow.i64', 'llvm.trap') for name in calls), (compiler, calls)
        print('tuple_function_tail: implicit/explicit optimized LLVM identical PASS', flush=True)
    if fixture in ('block_reference_threading', 'block_state_threading', 'with_collection_append'):
        function = 'forward' if fixture == 'block_reference_threading' else 'update'
        for compiler in (stage0, stage1):
            ir = work / f'{Path(compiler).name}-reference-threading.ll'
            subprocess.run([compiler, '-emit', 'llvm', '-O0', '-o', str(ir), str(source)], check=True, timeout=60)
            text = ir.read_text()
            match = re.search(rf'define[^\n]*@{function}\([^\n]*\)\s*#?\d*\s*\{{(.*?)\n\}}', text, re.S)
            assert match, (compiler, f'missing {function}() in LLVM IR')
            body = match.group(1)
            if fixture == 'with_collection_append':
                assert not re.search(r'\b(?:load|store)\s+%[^,\n]*State', body), (compiler, body)
                continue
            assert not re.search(r'\b(?:load|store)\s+%[^,\n]*LargeState|@(?:llvm\.)?mem(?:cpy|move)', body), (compiler, body)
        print(f'{fixture}: O0 LLVM has no aggregate load/store', flush=True)
# Keep lexical boundaries and capture checking enforced while widening valid forms.
state_prefix = 'struct State:\n    value: mutable i64\n\nstruct Handle:\n    kind: i64\n\n'
for name, body in {
    'tuple_tail_wrong_arity': '    1, 2\n',
    'tuple_tail_scope_escape': '    a, b =\n        hidden: i64 = 42\n        hidden, hidden + 1\n    return hidden\n',
    'append_region_escape': '    region outer(8192):\n        rows: mutable darray[darray[i64]] @outer = []\n        region short(4096):\n            row: darray[i64] @short = [1]\n            rows += row\n    return 0\n',
    'append_bulk': '    xs: mutable darray[i64] = []\n    xs += [1, 2]\n    return 0\n',
    'append_wrong_element': '    xs: mutable darray[i64] = []\n    xs += true\n    return 0\n',
    'append_immutable': '    xs: darray[i64] = [1]\n    xs += 2\n    return 0\n',
    'optional_match_hole': '    v: Handle? = null\n    x: i64 =\n        match v:\n            b if b.kind > 0:\n                b.kind\n            b:\n                0\n    return x\n',
    'state_unrelated_mutation': '    state: mutable State = zeroed\n    other: mutable i64 = 0\n    state <-\n        other <- 1\n        state.value <- 2\n        state\n    return 0\n',
    'state_mixed_result': '    state: mutable State = zeroed\n    other: State = zeroed\n    state <-\n        state.value <- 2\n        if state.value == 2:\n            state\n        else:\n            other\n    return 0\n',
    'state_leaked_local': '    state: mutable State = zeroed\n    state <-\n        hidden: i64 = 2\n        state.value <- hidden\n        state\n    return hidden\n',
    'leaked_local': '    value: i64 =\n        hidden: i64 = 42\n        hidden\n    return hidden\n',
    'uncaptured_mutation': '    outer: mutable i64 = 0\n    value: i64 =\n        outer <- 42\n        outer\n    return value\n',
    'immutable_capture': '    outer: i64 = 1\n    value: i64 = |outer|\n        outer <- 42\n        outer\n    return value\n',
}.items():
    source = work / (name + '.elisa')
    source.write_text(state_prefix + 'def main() -> i64:\n' + body)
    rejections = []
    for compiler in (stage0, stage1):
        result = subprocess.run([compiler, '-emit', 'obj', '-o', str(work/'invalid.o'), str(source)], capture_output=True, timeout=60)
        assert result.returncode == 1, (name, compiler, result.returncode, result.stderr)
        rejections.append(result.stderr)
    if name == 'optional_match_hole':
        assert rejections[0] == rejections[1], rejections
    print(f'{name}: stage0/stage1 rejection PASS', flush=True)
PY
