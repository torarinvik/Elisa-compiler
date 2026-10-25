"""Bind unbounded generic field checks to exact declaration owners."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_field_access_type_param.elisa"
FIXTURE = ROOT / "test/repro/field_access_generic_owner.elisa"
SMOKE = ROOT / "test/parity/field_access_generic_owner_smoke.sh"
GATE = ROOT / "test/parity/diagnostics_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
gate = GATE.read_text()

generic_lookup = function_source(source, "fatp_unbounded_type_params")
if not all(fragment in generic_lookup for fragment in (
    "owner_offsets: darray[u32]&",
    "names.count != lines.count",
    "names.count != owner_offsets.count",
    "lines[index] == bound_marker and owner_offsets[index] == owner_offset",
    "lines[index] == line and owner_offsets[index] == owner_offset",
)):
    raise SystemExit("field-access generic lookup must match exact owner rows and aligned metadata")

declaration_walk = function_source(source, "fatp_walk_decls")
if not all(fragment in declaration_walk for fragment in (
    "gp_owner_offsets: darray[u32]&",
    "line.line, line.offset, type_params",
    "module_body, gp_names, gp_lines, gp_owner_offsets, func_names, table",
    "scoped_body, gp_names, gp_lines, gp_owner_offsets, func_names, table",
)) or "file.generic_param_owner_offsets" not in source:
    raise SystemExit("field-access declaration walk must thread parser-owned offsets into nested scopes")

if fixture.count("#line 0 ") != 2 or \
        "def generic[T](value: T)" not in fixture or \
        "def concrete(value: T)" not in fixture or \
        "return value.missing" not in fixture or \
        "return value.good" not in fixture:
    raise SystemExit("fixture must distinguish a generic error from a same-line concrete struct access")
if 'python3 "$REPO_ROOT/test/proofs/check_field_access_generic_owner.py"' not in smoke or \
        "field access requires struct type, got T" not in smoke or \
        'bash "$REPO_ROOT/test/parity/field_access_generic_owner_smoke.sh"' not in gate:
    raise SystemExit("field-access smoke must run the owner proof and check the generic diagnostic")
