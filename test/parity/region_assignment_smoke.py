#!/usr/bin/env python3
"""Preserve allocation-local region reports and acceptance through traversal changes.

Exact negative rows capture current overlapping region diagnostics; this is an
optimization comparison gate, not a claim that duplicate reports are desirable.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    ('direct_escape', '''def escape() -> u32&:
    region short(4096):
        value: u32& = new[short] 7
        return value
''', [('530', '4'), ('260', '4'), ('260', '4')]),
    ('unrelated_declaration', '''def escape() -> u32&:
    region short(4096):
        value: u32& = new[short] 7
        unrelated: u32 = 5
        return value
''', [('530', '5'), ('260', '5'), ('260', '5')]),
    ('scalar_result', '''def safe() -> u32:
    region short(4096):
        value: u32& = new[short] 7
        return 5
''', []),
    ('unrelated_allocation', '''def safe(value: u32&) -> u32&:
    region short(4096):
        unrelated: u32& = new[short] 7
        return value
''', []),
)
FIXTURES = (
    ('new_region_owner_resolved.neg.elisa', []),
    ('region_param_bare_return.pos.elisa', []),
    ('region_param_bare_return.neg.elisa', [('261', '7'), ('261', '11'), ('261', '15'), ('261', '20')]),
)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: region_assignment_smoke.py /path/to/check_native')
    checker = str(Path(sys.argv[1]).resolve())
    cases = list(CASES) + [(name, (ROOT / 'test/fixtures/diagnostics' / name).read_text(), rows) for name, rows in FIXTURES]
    for name, source, expected in cases:
        result = subprocess.run([checker], input=source, text=True, capture_output=True, timeout=30)
        output = result.stdout + result.stderr
        records = re.findall(r'^(\d+):(\d+): (.*)$', output, re.MULTILINE)
        if (result.returncode != int(bool(expected)) or 'parse-errors=0' not in output.splitlines()
                or f'diagnostics={len(expected)}' not in output.splitlines()
                or [(kind, line) for kind, line, _ in records] != expected
                or any('region' not in message for _, _, message in records)):
            raise SystemExit(f'{name}: changed region result\n{output}')
        print(f'region assignment {name}: ok')


if __name__ == '__main__':
    main()
