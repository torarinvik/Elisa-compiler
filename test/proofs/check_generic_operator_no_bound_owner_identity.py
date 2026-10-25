"""Bind unbound generic operator checks to exact function declaration identity."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_generic_operator_no_bound.elisa"
SMOKE = ROOT / "test/parity/diagnostics_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
smoke = SMOKE.read_text()
sole_param = function_source(source, "gonb_sole_param_name")
bound_check = function_source(source, "gonb_param_has_any_bound")
walker = function_source(source, "gonb_walk_declarations")

if not all(fragment in sole_param for fragment in (
    "function_offset: u32",
    "table.generic_param_owner_offsets[index] == function_offset",
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
)):
    raise SystemExit("sole generic-parameter lookup must match the declaration offset")
if not all(fragment in bound_check for fragment in (
    "function_offset: u32",
    "table.generic_param_owner_offsets[generic_index] == function_offset",
    "table.generic_param_lines[generic_index] == encoded",
)):
    raise SystemExit("bound lookup must match the exact generic function owner")
if not all(fragment in walker for fragment in (
    "gonb_sole_param_name(table, decl_line.line, decl_line.offset)",
    "gonb_param_has_any_bound(table, decl_line.line, decl_line.offset)",
)):
    raise SystemExit("declaration walk must pass the active function offset")
if not all(fragment in smoke for fragment in (
    "#line 0 generic_owner.elisa\\ndef phantom[T]()",
    "#line 0 concrete_owner.elisa\\ndef concrete_sum(a: T, b: T)",
    "operator requires numeric operands",
    "#line 0 bounded_owner.elisa\\ndef evidence[T: Add]",
    "#line 0 unbound_owner.elisa\\ndef bad[U]",
    "same-line bounded owner suppressed the unbound function's operator diagnostic",
)):
    raise SystemExit("generic operator smoke must reject cross-declaration parameter borrowing at line zero")
