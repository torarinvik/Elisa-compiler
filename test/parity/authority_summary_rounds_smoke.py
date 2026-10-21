#!/usr/bin/env python3
"""Preserve current return-summary results while changing which bodies are revisited.

Deep-chain, recursive and mixed-global zero-report cases document existing opaque
summary policy/limitations; they do not assert that the resulting alias tracking is
complete. Revisit those baselines separately when that policy is changed.
"""
from pathlib import Path
import os
import re
import subprocess
import sys

BASE = '''global mutable counter: i64 = 0
def pointer() -> mutable void& can[Global{Read,Write}, Unsafe.PointerCast]:
    can Global{Read,Write}, Unsafe.PointerCast:
        return (&counter).cast[mutable void&]
def caller() -> void can[Global{Read,Write}, Unsafe.PointerCast]:
    raw: mutable void& = pointer() can Global{Read,Write}, Unsafe.PointerCast
    value: mutable i64& = raw.cast[mutable i64&] can Global.Read, Unsafe.PointerCast
    value <- 1
def main() -> i32:
    return 0
'''


def cases():
    yield 'direct', BASE, True
    for depth in (1, 2, 3, 4, 8):
        wrappers, previous = '', 'pointer'
        for index in range(depth):
            name = f'wrap{index}'
            wrappers += f'''def {name}() -> mutable void& can[Global{{Read,Write}}, Unsafe.PointerCast]:
    return {previous}() can Global{{Read,Write}}, Unsafe.PointerCast
'''
            previous = name
        source = BASE.replace('def caller()', wrappers + 'def caller()').replace(
            'raw: mutable void& = pointer()', 'raw: mutable void& = ' + previous + '()')
        yield f'chain_{depth}', source, depth < 4
        if depth == 3:
            head, tail = source.split('def caller()', 1)
            yield 'forward_chain', ('global mutable counter: i64 = 0\ndef caller()'
                  + tail.split('def main()', 1)[0] + head.split('\n', 1)[1]
                  + 'def main()' + tail.split('def main()', 1)[1]), True
            yield 'granted_chain', source.replace(
                'can Global.Read, Unsafe.PointerCast\n    value <- 1',
                'can Global{Read,Write}, Unsafe.PointerCast\n    can Global.Write:\n        value <- 1'), False
    identity = '''def identity(value: mutable void&) -> mutable void&:
    return value
'''
    yield 'argument_origin', BASE.replace('def caller()', identity + 'def caller()').replace(
        'raw: mutable void& = pointer()',
        'raw: mutable void& = identity(pointer() can Global{Read,Write}, Unsafe.PointerCast)'), True
    yield 'overload', BASE.replace('def pointer()', 'def pointer(flag: bool)').replace(
        'def caller()', '''def pointer(flag: i64) -> mutable void& can[Global{Read,Write}, Unsafe.PointerCast]:
    can Global{Read,Write}, Unsafe.PointerCast:
        return (&counter).cast[mutable void&]
def caller()''').replace('raw: mutable void& = pointer()', 'raw: mutable void& = pointer(true)'), True
    yield 'recursive', BASE.replace('def pointer()', 'def pointer(flag: bool)').replace(
        '        return (&counter).cast[mutable void&]',
        '        if flag:\n            return (&counter).cast[mutable void&]\n        return pointer(true)').replace(
        'raw: mutable void& = pointer()', 'raw: mutable void& = pointer(false)'), False
    yield 'opaque', BASE.replace(
        'def pointer() -> mutable void& can[Global{Read,Write}, Unsafe.PointerCast]:\n'
        '    can Global{Read,Write}, Unsafe.PointerCast:\n'
        '        return (&counter).cast[mutable void&]',
        'extern pointer() -> mutable void& can[Global{Read,Write}, Unsafe.PointerCast]'), False
    yield 'mixed_global', BASE.replace('global mutable counter: i64 = 0',
        'global mutable counter: i64 = 0\nglobal mutable other: i64 = 0').replace(
        'def pointer()', 'def pointer(flag: bool)').replace(
        '        return (&counter).cast[mutable void&]',
        '        if flag:\n            return (&counter).cast[mutable void&]\n        return (&other).cast[mutable void&]').replace(
        'raw: mutable void& = pointer()', 'raw: mutable void& = pointer(true)'), False


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: authority_summary_rounds_smoke.py /path/to/check_native')
    checker = str(Path(sys.argv[1]).resolve())
    environment = dict(os.environ)
    environment.pop('ELISA_STAGE1_TIMINGS', None)
    environment.pop('ELISA_AUTHORITY_FULL_SUMMARIES', None)
    reference_environment = dict(environment, ELISA_AUTHORITY_FULL_SUMMARIES='1')
    for name, source, reports_write in cases():
        result = subprocess.run([checker], input=source, text=True, capture_output=True, timeout=30, env=environment)
        reference = subprocess.run([checker], input=source, text=True, capture_output=True, timeout=30, env=reference_environment)
        if (result.returncode, result.stdout, result.stderr) != (reference.returncode, reference.stdout, reference.stderr):
            raise SystemExit(f'{name}: dependency/full summary modes differ\ndependency:\n{result.stdout}{result.stderr}\nfull:\n{reference.stdout}{reference.stderr}')
        output = result.stdout + result.stderr
        count = 2 if reports_write else 0
        records = re.findall(r'^(\d+):(\d+): (.*)$', output, re.MULTILINE)
        expected_lines = [str(index) for index, line in enumerate(source.splitlines(), 1)
                          if line.startswith('    value:') or line == '    value <- 1'] if reports_write else []
        good = (result.returncode == int(reports_write) and 'parse-errors=0' in output.splitlines()
                and f'diagnostics={count}' in output.splitlines() and len(records) == count
                and [line for _, line, _ in records] == expected_lines
                and all(kind == '404' and 'without Global.Write' in message for kind, _, message in records))
        if not good:
            raise SystemExit(f'{name}: changed return-summary result\n{output}')
        print(f'authority summary {name}: ok')


if __name__ == '__main__':
    main()
