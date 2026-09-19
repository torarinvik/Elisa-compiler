#!/usr/bin/env bash
# Unknown nominal names must fail before code generation, while contextual receiver
# and state names remain legal. Check both native compilers, including diagnostics.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

python3 - "$ELISACORE_BIN" "$STAGE1" <<'PY'
import pathlib
import re
import subprocess
import sys
import tempfile
import textwrap

compilers = sys.argv[1:]
impl = '''\
protocol Identity:
    def identity(self: Self) -> Self
struct Item:
    value: i64
impl Identity for Item:
    def identity(self: Self) -> Self:
        copy: Self = self
        return copy
'''
cases = [
    ("impl_self", impl, None),
    ("module_impl_self", "module Example:\n" + textwrap.indent(impl, "    "), None),
    ("inherent_self", '''\
struct Item:
    value: i64
impl Item:
    def identity(self: Self) -> Self:
        return self
''', None),
    ("impl_nested_self", '''\
protocol Identity:
    def identity(self: Self&) -> Self&
struct Item:
    value: i64
impl Identity for Item:
    def identity(self: Self&) -> Self&:
        return self
''', None),
    ("declared_generic", "def identity[Element](value: Element) -> Element:\n    return value\n", None),
    ("unknown_parameter", "def bad(value: Missing) -> void:\n    pass\n", 'unknown type "Missing"'),
    ("unknown_field", "struct Item:\n    value: Missing\n", 'unknown type "Missing"'),
    ("unknown_element", "def bad(value: darray[Missing]) -> void:\n    pass\n", 'unknown type "Missing"'),
    ("free_self_after_impl", impl + "def bad(value: Self) -> Self:\n    return value\n", 'unknown type "Self"'),
    ("nested_free_self", impl + "def bad(value: darray[Self]) -> void:\n    pass\n", 'unknown type "Self"'),
    ("field_self_after_impl", impl + "struct Bad:\n    value: Self\n", 'unknown type "Self"'),
    ("impl_unknown_parameter", impl.replace("copy: Self", "copy: Missing"), 'unknown type "Missing"'),
]

with tempfile.TemporaryDirectory(prefix="elisa-unknown-types-") as directory:
    work = pathlib.Path(directory)
    for name, source, diagnostic in cases:
        path = work / f"{name}.elisa"
        path.write_text(source + "\ndef main() -> i64:\n    return 0\n", encoding="utf-8")
        unknowns = []
        for index, compiler in enumerate(compilers):
            result = subprocess.run(
                [compiler, "-emit", "obj", "-o", str(work / f"{name}.{index}.o"), str(path)],
                capture_output=True, text=True, timeout=60,
            )
            output = result.stdout + result.stderr
            if diagnostic is None:
                assert result.returncode == 0, (name, compiler, result.returncode, output)
            else:
                assert result.returncode == 1 and diagnostic in output, (name, compiler, result.returncode, output)
            unknowns.append(re.findall(r':(\d+:\d+-\d+): (unknown type "[^"]+")', output))
        assert unknowns[0] == unknowns[1], (name, unknowns)

print(f"unknown-type smoke OK: {len(cases)} cases agree on acceptance and unknown-type spans")
PY
