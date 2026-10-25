"""Bind generic UFCS receiver ranks to the exact candidate declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER_TYPES = ROOT / "src/parser/parser_tokens.elisa"
PARSER_FUNCTIONS = ROOT / "src/parser/parser_types_function.elisa"
AUTHORITY = ROOT / "src/semantic/check_global_authority.elisa"
AUTHORITY_TYPES = ROOT / "src/semantic/check_global_authority_types_references.elisa"
AUTHORITY_ROWS = ROOT / "src/semantic/check_global_authority_rows.elisa"
AUTHORITY_INCREMENTAL = ROOT / "src/semantic/check_global_authority/incremental.elisa"
GLOBAL_PERMISSIONS = ROOT / "src/semantic/check_global_permissions/axis_projection.elisa"
SMOKE = ROOT / "test/parity/global_overload_authority_smoke.py"
FIXTURE = ROOT / "test/repro/global_authority_generic_receiver_rank_line_zero.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing global-authority helper {name}")
    return match.group(0)


parser_types = PARSER_TYPES.read_text()
parser_functions = PARSER_FUNCTIONS.read_text()
authority = AUTHORITY.read_text()
authority_types = AUTHORITY_TYPES.read_text()
authority_rows = AUTHORITY_ROWS.read_text()
incremental = AUTHORITY_INCREMENTAL.read_text()
permissions = GLOBAL_PERMISSIONS.read_text()
smoke = SMOKE.read_text()
fixture = FIXTURE.read_text()
receiver_rank = function_source(authority_types, "ga_method_receiver_rank")
canonical_context = function_source(authority_rows, "canonical_effect_context")

if "generic_param_owner_offsets: darray[u32]" not in parser_types or not all(fragment in parser_functions for fragment in (
    "parser.generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(function_offset) if is_generic_name",
    'name: "__generic_param_identity"',
    "detail_line: function_line",
    "offset: function_offset",
)):
    raise SystemExit("parser generic owner offsets must remain aligned with function generic rows")
if "generic_owner_offsets: darray[u32] = []" not in authority:
    raise SystemExit("GlobalAuthority must retain the generic owner-offset column")
if "generic_owner_offsets: file.generic_param_owner_offsets" not in incremental or \
        "generic_owner_offsets: file.generic_param_owner_offsets" not in permissions or not all(fragment in canonical_context for fragment in (
    "state.generic_lines <- table.generic_param_lines",
    "state.generic_names <- table.generic_param_names",
    "state.generic_owner_offsets <- table.generic_param_owner_offsets",
)):
    raise SystemExit("all GlobalAuthority construction paths must receive aligned parser owner offsets")

if not all(fragment in receiver_rank for fragment in (
    "candidate >= state.function_offsets.count",
    "offset: u32 = state.function_offsets[candidate]",
    "state.function_offsets[other] == offset",
    "state.generic_lines.count != state.generic_names.count or state.generic_lines.count != state.generic_owner_offsets.count",
    "state.generic_lines[index] == line",
    "state.generic_owner_offsets[index] == offset",
    "state.generic_names[index] == formal_head",
)) or "state.function_lines[other] == line" in receiver_rank and "state.function_offsets[other] == offset" not in receiver_rank:
    raise SystemExit("generic receiver rank must select the candidate's exact line/offset owner")

if fixture.count("#line 0 ") != 2 or not all(fragment in fixture for fragment in (
    "#line 0 generic-receiver-candidate.elisa\ndef peek[T](self: T)",
    "#line 0 concrete-receiver-candidate.elisa\ndef peek(self: Concrete)",
    "can Global.Read:\n        return hot",
    "return value.peek()",
)):
    raise SystemExit("fixture must place a generic and concrete UFCS overload on one logical line")
if "check_global_authority_generic_receiver_rank.py" not in smoke or \
        "global_authority_generic_receiver_rank_line_zero.elisa" not in smoke or \
        "generic receiver rank uses exact owner at line zero" not in smoke:
    raise SystemExit("global overload smoke must check the line-zero receiver-rank regression")
print("global authority generic receiver-rank source proof OK")
