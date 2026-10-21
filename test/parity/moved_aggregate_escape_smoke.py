#!/usr/bin/env python3
"""Check moved aggregate region escapes through the actual compiler CLI."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
compiler = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))
prefix = "struct Report:\n    entries: mutable darray[u32] = []\n"
cases = []
for name, result_type, value in (
    ("plain", "Report", "report"),
    ("move", "Report", "move report"),
    ("parenthesized_move", "Report", "(move report)"),
    ("nested_move", "darray[Report]", "[move report]"),
):
    cases.append((name, prefix + f'''def invalid() -> {result_type}:
    can Memory.Allocate, Abort.Panic:
        region short(4096):
            report: mutable Report = Report{{entries: []}}
            report.entries.push(17)
            return {value}
''', True))
for name, declaration, arena in (
    ("caller_owned", "def valid(arena: mutable Arena&) -> Report:", "arena"),
    ("program_owned", "global region stable\ndef valid() -> Report:", "stable"),
):
    cases.append((name, prefix + declaration + f'''
    can Memory.Allocate, Abort.Panic:
        in {arena}:
            report: mutable Report = Report{{entries: []}}
            report.entries.push(17)
            return move report
''', False))
with tempfile.TemporaryDirectory(prefix="elisa-move-escape-") as directory:
    directory = Path(directory)
    for name, source, reject in cases:
        path = directory / (name + ".elisa")
        path.write_text(source)
        result = subprocess.run(
            [compiler, "-emit", "iface", "-permissive", "-O0", "-o", str(directory / (name + ".iface.elisa")), str(path)],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout + result.stderr
        passed = (result.returncode == 1 and 'scope-owned region "short" escapes via return' in output
                  if reject else result.returncode == 0)
        if not passed:
            raise SystemExit(f"{name}: wrong escape result ({result.returncode})\n{output}")
        print(f"moved aggregate {name}: ok")
