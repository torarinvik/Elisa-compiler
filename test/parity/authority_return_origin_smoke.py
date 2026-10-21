#!/usr/bin/env python3
"""Keep global return origins through void pointers during summary optimization."""
from pathlib import Path
import re
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: authority_return_origin_smoke.py /path/to/check_native")
checker = str(Path(sys.argv[1]).resolve())
source = '''global mutable counter: i64 = 0
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
result = subprocess.run([checker], input=source, text=True, capture_output=True, timeout=30)
output = result.stdout + result.stderr
records = re.findall(r"^(\d+):(\d+): (.*)$", output, re.MULTILINE)
if (result.returncode != 1 or "parse-errors=0" not in output.splitlines()
        or "diagnostics=2" not in output.splitlines()
        or [(kind, line) for kind, line, _ in records] != [("404", "7"), ("404", "8")]
        or any("without Global.Write" not in message for _, _, message in records)):
    raise SystemExit("void pointer return lost global write origin:\n" + output)
print("native checker void pointer global return origin: ok")

# Matching local grants permit both the pointer cast and the write.
granted = source.replace(
    "can Global.Read, Unsafe.PointerCast\n    value <- 1",
    "can Global{Read,Write}, Unsafe.PointerCast\n    can Global.Write:\n        value <- 1",
)
result = subprocess.run([checker], input=granted, text=True, capture_output=True, timeout=30)
output = result.stdout + result.stderr
if result.returncode != 0 or "parse-errors=0" not in output.splitlines() or "diagnostics=0" not in output.splitlines():
    raise SystemExit("granted void pointer return was rejected:\n" + output)
print("native checker granted void pointer global return: ok")

# A primitive spelling can name a reference alias; builtin recognition must not
# discard this source-defined return origin during summary shortcuts.
aliased = source.replace('global mutable counter: i64 = 0',
    'alias i64 = mutable void&\nglobal mutable counter: u32 = 0').replace(
    'def pointer() -> mutable void&', 'def pointer() -> i64').replace(
    'raw: mutable void&', 'raw: i64').replace(
    'value: mutable i64& = raw.cast[mutable i64&]', 'value: mutable u32& = raw.cast[mutable u32&]')
result = subprocess.run([checker], input=aliased, text=True, capture_output=True, timeout=30)
output = result.stdout + result.stderr
records = re.findall(r"^(\d+):(\d+): (.*)$", output, re.MULTILINE)
if (result.returncode != 1 or "parse-errors=0" not in output.splitlines()
        or "diagnostics=2" not in output.splitlines()
        or [(kind, line) for kind, line, _ in records] != [("404", "8"), ("404", "9")]
        or any("without Global.Write" not in message for _, _, message in records)):
    raise SystemExit("primitive-spelling alias lost global return origin:\n" + output)
print("native checker primitive-spelling reference alias origin: ok")
