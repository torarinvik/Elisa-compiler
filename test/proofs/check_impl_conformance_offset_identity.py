"""Bind impl error-set conformance rows to exact declaration offsets."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_impl_conformance.elisa"
PARSER = ROOT / "src/parser/parser_types_function.elisa"
FIXTURE = ROOT / "test/repro/impl_error_set_offset_identity.elisa"
SMOKE = ROOT / "test/parity/qualified_error_set_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
parser = PARSER.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
identity = function_source(source, "imc_function_identity")
occurrence = function_source(source, "imc_function_error_occurrence")
module = function_source(source, "imc_function_module")
error_check = function_source(source, "imc_check_errors")

for selector, label in ((identity, "identity"), (occurrence, "return occurrence"), (module, "function module")):
    if "annotation.offset != function_pos.offset" not in selector and "annotation.offset == function_pos.offset" not in selector:
        raise SystemExit(f"impl {label} selector must compare the exact declaration offset")
    if "function_pos.offset == 0" in selector or "annotation.offset == 0" in selector:
        raise SystemExit(f"impl {label} selector must treat byte offset zero as a valid position")
if "annotation.offset == func_line.offset" not in error_check or "func_line.offset == 0" in error_check or "annotation.offset == 0" in error_check:
    raise SystemExit("impl family rows must match the exact method declaration offset, including zero")
if 'name: "__error_return", line: token.line, offset: token.start' not in parser:
    raise SystemExit("parser must retain the function token offset on the return marker")
if 'owner: "__fn_module", name: parser.current_module, line: token.line, offset: token.start' not in parser:
    raise SystemExit("parser must retain the same function token offset on module provenance")
if not fixture.startswith("def push(") or not all(fragment in fixture for fragment in (
        "error[Allowed]",
        "#line 1 same-offset-impl.elisa",
        "impl Sink for Log:",
        "def push(value: i64) -> i64 error[Extra]:")):
    raise SystemExit("fixture must pair a byte-zero declaration with a same-#line impl method")
if 'impl_error_set_offset_identity.elisa' not in smoke or 'impl method "push" for interface "Sink" raises error' not in smoke:
    raise SystemExit("parity smoke must assert the extra impl ErrorSet remains attached to its method")

print('{"source_bound": true, "impl_error_declaration_offsets": true}')
