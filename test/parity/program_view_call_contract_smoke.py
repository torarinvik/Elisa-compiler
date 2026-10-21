#!/usr/bin/env python3
"""Check source-view caller contracts through positional and named arguments."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))
PREFIX = '''global region source
def remember(names: mutable darray[sview @source]&, text: sview @source) -> void:
    can Memory.Allocate, Abort.Panic:
        names.push(text)
'''

failures = []
with tempfile.TemporaryDirectory(prefix="elisa-program-view-call-") as directory:
    directory = Path(directory)
    for name, expression, reject in (
        ("literal", '"safe"', False),
        ("program_parameter", "stable", False),
        ("short_view", "bytes.as_sview()", True),
        ("borrowed_parameter", "borrowed", True),
    ):
        for named in (False, True):
            label = name + ("_named" if named else "_positional")
            call = f"remember(text: {expression}, names: names)" if named else f"remember(names, {expression})"
            source = PREFIX + '''def caller(stable: sview @source, borrowed: sview) -> void:
    can Memory.Allocate, Abort.Panic:
        names: mutable darray[sview @source] = []
        region short(4096):
            bytes: mutable darray[u8] @short = [65]
            ''' + call + '''
def main() -> i32:
    return 0
'''
            path = directory / (label + ".elisa")
            path.write_text(source)
            result = subprocess.run(
                [COMPILER, "-emit", "obj", "-permissive", "-O0", "-o", str(directory / (label + ".o")), str(path)],
                capture_output=True, text=True, timeout=30,
            )
            diagnostics = result.stdout + result.stderr
            rejected_for_lifetime = result.returncode != 0 and "region" in diagnostics
            passed = rejected_for_lifetime if reject else result.returncode == 0
            print(("PASS " if passed else "FAIL ") + label)
            if not passed:
                failures.append((label, result.returncode, diagnostics))
    for name, element_type, item, reject in (
        ("source_elements_local_buffer", "sview @source", '"safe"', False),
        ("short_elements_local_buffer", "sview", "bytes.as_sview()", True),
    ):
        for named in (False, True):
            label = name + ("_named" if named else "_positional")
            call = "first_name(names: names, ignore: false)" if named else "first_name(false, names)"
            source = f"""global region source
def first_name(ignore: bool, names: darray[sview @source]&) -> sview @source:
    can Abort.Panic:
        return names[0]
def main() -> i32:
    can Memory.Allocate, Abort.Panic:
        region short(4096):
            bytes: mutable darray[u8] @short = [65]
            names: mutable darray[{element_type}] = [{item}]
            value: sview @source = {call}
        return 0
"""
            path = directory / (label + ".elisa")
            path.write_text(source)
            result = subprocess.run(
                [COMPILER, "-emit", "obj", "-permissive", "-O0", "-o", str(directory / (label + ".o")), str(path)],
                capture_output=True, text=True, timeout=30,
            )
            diagnostics = result.stdout + result.stderr
            passed = result.returncode != 0 and "region" in diagnostics if reject else result.returncode == 0
            print(("PASS " if passed else "FAIL ") + label)
            if not passed:
                failures.append((label, result.returncode, diagnostics))
for label, status, diagnostics in failures:
    print(f"{label}: exit={status}\n{diagnostics}")
if failures:
    raise SystemExit(1)
