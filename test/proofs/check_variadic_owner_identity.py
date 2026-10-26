"""Variadic function metadata must be joined to the declaration token."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_func_params.elisa").read_text()
SYMBOLS = (ROOT / "src/semantic/symbols.elisa").read_text()
BACKEND = (ROOT / "src/backend/codegen_declare_signature.elisa").read_text()
CALLABLE_ROWS = (ROOT / "src/semantic/check_try_fallible/callable_rows.elisa").read_text()
AST_TESTS = (ROOT / "test/parity/parser_ast_decls.elisa").read_text()
FIXTURE = (ROOT / "test/repro/variadic_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/variadic_owner_line_zero_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*def {re.escape(name)}\(.*?(?=^\s*def |^\s*public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


recorder = function_source(PARSER, "record_variadic_marker")
param_list = function_source(PARSER, "parse_param_list")
symbol_lookup = function_source(SYMBOLS, "function_is_variadic")
backend_lookup = function_source(BACKEND, "function_is_variadic")

if "function_offset: u32" not in recorder or \
        'line: function_line, offset: function_offset' not in recorder or \
        "record_variadic_marker(function_line, function_offset)" not in param_list:
    raise SystemExit("parser variadic marker must retain the owning function offset")
for source, label in ((symbol_lookup, "symbol collection"), (backend_lookup, "LLVM declaration")):
    if "annotation.line == line and annotation.offset == owner_offset" not in source:
        raise SystemExit(f"{label} must match variadic metadata by declaration line and offset")
if "marker.line == function_position.line and marker.offset == function_position.offset" not in CALLABLE_ROWS:
    raise SystemExit("callable fact collection must match variadic metadata to the function position")
for path in (ROOT / "src").rglob("*.elisa"):
    for source_line in path.read_text().splitlines():
        if 'owner == "__variadic"' in source_line and ".line" in source_line and ".offset" not in source_line:
            raise SystemExit(f"line-only variadic consumer remains: {path}: {source_line.strip()}")
if "test_variadic_marker_uses_function_owner_offset" not in AST_TESTS or \
        FIXTURE.count("#line 0 variadic-owner.elisa") != 2 or \
        "def takes_tail(value: i64, ...) -> void:" not in FIXTURE or \
        "def takes_fixed(value: i64) -> void:" not in FIXTURE:
    raise SystemExit("line-zero regression must distinguish a variadic function from a fixed sibling")
if "variadic_owner_line_zero.elisa" not in SMOKE or \
        "function \"fixed\" expects 1 arguments, got 2" not in SMOKE or \
        "check_variadic_owner_identity.py" not in SMOKE:
    raise SystemExit("variadic smoke must prove the fixed sibling does not inherit the variadic tail")

print("variadic owner-offset source checks passed")
