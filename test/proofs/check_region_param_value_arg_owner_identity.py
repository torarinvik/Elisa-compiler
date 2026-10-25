"""Bind region-parameter value-argument checks to exact caller and callee owners."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "src/semantic/check_region_param_value_arg.elisa"
SMOKE = ROOT / "test/parity/diagnostics_smoke.sh"
POS = ROOT / "test/repro/region_param_value_arg_owner_line_zero.pos.elisa"
NEG = ROOT / "test/repro/region_param_value_arg_owner_line_zero.neg.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


checker = CHECKER.read_text()
smoke = SMOKE.read_text()
positive = POS.read_text()
negative = NEG.read_text()

find_func = function_source(checker, "rgv_find_func")
has_region_param = function_source(checker, "rgv_function_has_region_param")
check_call = function_source(checker, "rgv_check_call")
check_func = function_source(checker, "rgv_check_func")
collect_callees = function_source(checker, "check_region_param_value_arg")
if "offset: mutable u32 = 0" not in checker or \
        "function_offset: mutable u32 = 0" not in checker:
    raise SystemExit("region argument scope and callee records must retain function offsets")
if not all(fragment in find_func for fragment in (
    "result.offset <- function_pos.offset",
    "result.offset <- inner_pos.offset",
    "result.found <- result.count == 1",
)) or "result.line != 0" in find_func:
    raise SystemExit("callee lookup must retain exact offsets and accept line-zero declarations")
if not all(fragment in has_region_param for fragment in (
    'row.name == "__region_param"',
    "row.line == line",
    "row.owner_offset == offset",
)):
    raise SystemExit("region callee discovery must match the annotation owner offset")
if not all(fragment in check_call for fragment in (
    "row.owner_offset == target.offset",
    "rgv_function_has_region_param(file.local_region_annotations, target.line, target.offset)",
    "row.owner_offset >= rgs.function_offset",
    "row.owner_offset <= call_pos.offset",
    "row.end_offset == 0 or call_pos.offset < row.end_offset",
)):
    raise SystemExit("callee parameters and return guards must be owner scoped, and ambient rows source scoped")
if "function_offset: u32" not in check_func or \
        "row.owner_offset == function_offset" not in check_func or \
        "rgs.function_offset <- function_offset" not in check_func:
    raise SystemExit("caller region parameters must be collected for the exact function")
if "rgv_function_has_region_param(file.local_region_annotations, function_pos.line, function_pos.offset)" not in collect_callees or \
        "rgv_function_has_region_param(file.local_region_annotations, inner_function_pos.line, inner_function_pos.offset)" not in collect_callees:
    raise SystemExit("top-level and module callees must be selected by line and offset")

if not all(fragment in positive for fragment in (
    "#line 0 region-put.elisa",
    "#line 0 region-sibling.elisa",
    "#line 0 unbound-caller.elisa",
    "#line 0 unrelated-region-binder.elisa",
    "#line 0 unrelated-local-region.elisa",
    "def put[@r](value: i64& @r)",
    "def sibling[@r](value: i64& @r)",
    "region r(128):",
    "put(value)",
)):
    raise SystemExit("positive fixture must exercise same-line callee rows and an unbound line-zero caller")
if "#line 0 bound-caller.elisa" not in negative or \
        "def good[@r](value: i64)" not in negative or \
        "#line 0 local-region-caller.elisa" not in negative or \
        "region r(128)" not in negative or "put(value)" not in negative:
    raise SystemExit("negative fixture must preserve a caller's own and local line-zero region bindings")
if "check_region_param_value_arg_owner_identity.py" not in smoke or \
        "region_param_value_arg_owner_line_zero" not in smoke:
    raise SystemExit("diagnostics smoke must gate the owner proof and behavior fixtures")
