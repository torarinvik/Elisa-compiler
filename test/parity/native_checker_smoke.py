#!/usr/bin/env python3
"""Exercise complete native checker diagnostics; does not build the checker."""
from pathlib import Path
import re
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: native_checker_smoke.py /path/to/check_native")
checker = str(Path(sys.argv[1]).resolve())
cases = (
    ("clean", "def main() -> i32:\n    return 0\n", 0, ()),
    ("void_global_effects", """global mutable counter: u32 = 0
def touch() -> void:
    counter <- counter + 1
def caller() -> void:
    touch()
def main() -> i32:
    caller()
    return 0
""", 4, ('Global.Read', 'Global.Write', 'call to "touch"', 'call to "caller"')),
    ("scalar_global_effects", """global mutable counter: u32 = 0
def bump() -> u32:
    counter <- counter + 1
    return counter
def caller() -> u32:
    return bump()
def main() -> i32:
    return caller().i32()
""", 5, ('Global.Read', 'Global.Write', 'call to "bump"', 'call to "caller"')),
    ("undefined_name", "def main() -> i32:\n    return absent_name\n", 1,
     ('undefined identifier "absent_name"',)),
    ("readonly", '''def mutate(value: mutable i64&) -> void:
    value <- 1
def caller(value: i64&) -> void:
    mutate(value)
''', 2, ('to "mutate" expects', 'mutable i64&', 'got i64&')),
    ("error_union", '''error Problem:
    Failed
def fallible() -> i64 error[Problem]:
    raise Problem.Failed
def caller() -> void:
    fallible()
''', 1, ('error union result must be handled',)),
    ("exclusivity", '''def consume(left: mutable i64&, right: mutable i64&) -> void:
    pass
def caller() -> void:
    value: mutable i64 = 0
    consume(&value, &value)
''', 1, ('call "consume" passes "value"', 'overlapping memory')),
)
for name, source, expected_count, fragments in cases:
    result = subprocess.run([checker], input=source, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    expected_status = 1 if expected_count else 0
    if result.returncode != expected_status or "parse-errors=0" not in output.splitlines():
        raise SystemExit(f"{name}: unexpected status/parse result {result.returncode}\n{output}")
    summary = re.search(r"^diagnostics=(\d+)$", output, re.MULTILINE)
    records = re.findall(r"^(\d+):(\d+): (.*)$", output, re.MULTILINE)
    if summary is None or int(summary[1]) != expected_count or len(records) != expected_count:
        raise SystemExit(f"{name}: wrong diagnostic count\n{output}")
    if any(int(line) == 0 for _, line, _ in records):
        raise SystemExit(f"{name}: diagnostic record lost its source location\n{output}")
    if any(fragment not in output for fragment in fragments):
        raise SystemExit(f"{name}: diagnostic payload missing\n{output}")
    print(f"native checker {name}: ok")
