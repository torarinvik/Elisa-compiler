#!/usr/bin/env python3
"""Exercise buffer annotations, versioned imports, collisions and static call checking."""
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

from pymodule_pyi import render

manifest = {"functions": [
    {"name": "read", "parameters": [{"name": "values", "type": "view[f64]"}], "return": "f64"},
    {"name": "write", "parameters": [{"name": "values", "type": "view[f64]", "mutable": True}], "return": "void"},
    {"name": "text", "parameters": [{"name": "values", "type": "view[sview]"}], "return": "view[sview]"},
]}
with tempfile.TemporaryDirectory(prefix="elisa-buffer-stubs-") as directory:
    root = Path(directory)
    stub = render(manifest)
    (root / "arrays.pyi").write_text(stub)
    assert "def read(values: Sequence[float] | _elisa_buffers.Buffer) -> float" in stub
    assert "def write(values: _elisa_buffers.Buffer) -> None" in stub
    assert "def text(values: Sequence[str | bytes]) -> list[str]" in stub
    runpy.run_path(str(root / "arrays.pyi"))
    assert "class NotRequired" not in stub
    # Private import names must remain usable when exports choose those spellings.
    collision = {"functions": manifest["functions"] + [
        {"name": name, "parameters": [], "return": "void"}
        for name in ("_elisa_buffers", "_elisa_type_checking", "Buffer", "Sequence", "NotRequired",
                     "Any", "Final", "Iterable", "Literal", "Mapping", "Protocol", "TypedDict")
    ], "structs": [{"name": "Row", "fields": [{"name": "values", "type": "view[i64]"}, {"name": "optional", "type": "i64?", "optional": True}]}]}
    collided = render(collision)
    assert "import collections.abc as __elisa_buffers" in collided
    assert "__elisa_buffers.Buffer" in collided
    (root / "collisions.pyi").write_text(collided)
    runpy.run_path(str(root / "collisions.pyi"))
    scalar = render({"functions": [{"name": "identity", "parameters": [], "return": "i64"}]})
    assert "_elisa_buffers" not in scalar
    pyright = shutil.which("pyright")
    if pyright:
        valid = '''from array import array
from arrays import read, write, text

class Exporter:
    def __buffer__(self, flags: int, /) -> memoryview:
        return memoryview(bytearray(16))

read([1., 2.])
read(array('d', [1., 2.]))
read(memoryview(array('d', [1., 2.])))
read(Exporter())
write(array('d', [1., 2.]))
write(bytearray(16))
write(Exporter())
text(['one', b'two'])
'''
        (root / "valid.py").write_text(valid)
        (root / "invalid.py").write_text("from arrays import write\nwrite([1., 2.])\nwrite(object())\n")
        command = [pyright, "--pythonpath", sys.executable]
        for version in ("3.10", "3.12"):
            result = subprocess.run(command + ["--pythonversion", version, "--level", "error", "valid.py"],
                                    cwd=root, capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run(command + ["--pythonversion", "3.10", "--level", "error", "collisions.pyi"],
                                cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run(command + ["--pythonversion", "3.12", "--outputjson", "invalid.py"],
                                cwd=root, capture_output=True, text=True)
        report = json.loads(result.stdout)
        errors = [d for d in report["generalDiagnostics"] if d["severity"] == "error"]
        assert result.returncode != 0 and len(errors) == 2, report
        assert all(d["rule"] == "reportArgumentType" for d in errors), report
        print("buffer stub calls accepted; non-buffer writable arguments rejected")
    else:
        print("buffer stub static-call checks skipped (pyright unavailable)")
print("buffer stub rendering, runtime imports and name collisions passed")
