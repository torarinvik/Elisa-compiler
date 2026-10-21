#!/usr/bin/env python3
"""Verify OR constant selectors without exempting lexical or payload bindings."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if len(sys.argv) != 2:
    raise SystemExit("usage: scalar_or_constants_smoke.py /path/to/check_native")
checker = str(Path(sys.argv[1]).resolve())
constants = "const FIRST: u32 = 1\nconst SECOND: u32 = 2\n"
cases = (
    ("constant_forms", (ROOT / "test/fixtures/self_parse_syntax/scalar_constant_or_match.elisa").read_text(), False),
    ("module_constant", '''module Values:
    const FIRST: u32 = 1
    const SECOND: u32 = 2
    def select(value: u32) -> i32:
        return match value:
            FIRST or SECOND: 1
            _: 0
''', False),
    ("parameter_shadow", constants + '''def select(value: u32, FIRST: u32) -> i32:
    return match value:
        FIRST or SECOND: 1
        _: 0
''', True),
    ("local_shadow", constants + '''def select(value: u32) -> i32:
    FIRST: u32 = 9
    return match value:
        FIRST or SECOND: 1
        _: 0
''', True),
    ("unknown_bindings", '''def select(value: u32) -> i32:
    return match value:
        left or right: 1
        _: 0
''', True),
    ("wrong_constant_type", 'const FIRST: bool = true\nconst SECOND: bool = false\n' + '''def select(value: u32) -> i32:
    return match value:
        FIRST or SECOND: 1
        _: 0
''', True),
    ("char_selector_names", "const FIRST: char = 'a'\nconst SECOND: char = 'b'\n" + '''def select(value: char) -> i32:
    return match value:
        FIRST or SECOND: 1
        _: 0
''', True),
    ("partly_unresolved", constants + '''def select(value: u32) -> i32:
    return match value:
        FIRST or UNKNOWN: 1
        _: 0
''', True),
    ("payload_bindings", '''enum Choice:
    A(u32)
    B(u32)
def select(value: Choice) -> i32:
    return match value:
        Choice.A(left) or Choice.B(right): 1
        _: 0
''', True),
)
failures = []
for name, source, reject in cases:
    result = subprocess.run([checker], input=source, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    expected = "top-level or-pattern alternatives that bind names are not supported"
    summary = re.search(r"^diagnostics=(\d+)$", output, re.MULTILINE)
    passed = "parse-errors=0" in output.splitlines() and summary is not None
    passed = passed and (result.returncode == 1 and expected in output if reject else result.returncode == 0 and summary[1] == "0")
    if reject:
        expected_lines = [number for number, line in enumerate(source.splitlines(), 1) if " or " in line]
        actual_lines = [int(line) for line in re.findall(r"^609:(\d+): " + re.escape(expected) + r"$", output, re.MULTILINE)]
        passed = passed and actual_lines == expected_lines
    print(("PASS " if passed else "FAIL ") + name)
    if not passed:
        failures.append((name, output))
for name, output in failures:
    print(f"{name}:\n{output}")
if failures:
    raise SystemExit(1)
