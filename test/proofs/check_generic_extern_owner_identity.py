"""Generic extern metadata must pair to one declaration token, including #line 0."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_export_surface.elisa").read_text()
PAIRING = (ROOT / "src/backend/codegen_payload_enum_reg.elisa").read_text()
LOOKUP = (ROOT / "src/backend/codegen_abi_facts.elisa").read_text()
FIXTURE = (ROOT / "test/repro/generic_extern_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/generic_extern_owner_line_zero_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*def {re.escape(name)}\(.*?(?=^\s*def |^\s*public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


producer = function_source(PARSER, "parse_extern_signature_and_body")
if not all(
    fragment in producer
    for fragment in (
        'owner: "__extern_generic_param", name: extern_generic_param, line: token.line, offset: token.start',
        'owner: "__extern_generic_name", name: name, line: token.line, offset: token.start',
    )
):
    raise SystemExit("generic extern metadata rows must carry their declaration token offset")

pair_start = PAIRING.find("# Generic externs: pair the parameter and name rows")
if pair_start < 0:
    raise SystemExit("missing generic extern exact-owner pairing block")
pair_block = PAIRING[pair_start:PAIRING.find("\n\n\n", pair_start)]
if 'param_annotation.owner != "__extern_generic_param"' not in pair_block or \
        'name_annotation.owner != "__extern_generic_name"' not in pair_block or \
        "name_annotation.line != param_annotation.line" not in pair_block or \
        "name_annotation.offset != param_annotation.offset" not in pair_block:
    raise SystemExit("generic extern name/parameter rows must match both declaration line and offset")

# The fixture's physical declaration positions are distinct, even though its logical lines
# collide. The colliding logical line alone would produce four pairings; exact offsets leave
# only each parameter/name pair owned by the same extern token.
first_offset = fixture.index("extern first_record")
second_offset = fixture.index("extern second_record")
if first_offset == second_offset:
    raise SystemExit("same-line generic extern declarations must have distinct physical offsets")
param_rows = [("T", 0, first_offset), ("U", 0, second_offset)]
name_rows = [("first_record", 0, first_offset), ("second_record", 0, second_offset)]
paired_rows = [
    (param, name)
    for param, param_line, param_offset in param_rows
    for name, name_line, name_offset in name_rows
    if param_line == name_line and param_offset == name_offset
]
if paired_rows != [("T", "first_record"), ("U", "second_record")]:
    raise SystemExit("same-line generic extern owner model admitted a cross-pair")

lookup = function_source(LOOKUP, "generic_extern_param_of")
if "generic_extern_names.count != structs.annotations.generic_extern_params.count" not in lookup or \
        "return \"\" if found" not in lookup or \
        "selected_param <- structs.annotations.generic_extern_params[index]" not in lookup or \
        "return selected_param if found else \"\"" not in lookup:
    raise SystemExit("name-only generic extern lookup must fail closed on malformed or duplicate rows")

def unique_parameter(rows: list[tuple[str, str]], name: str) -> str:
    selected = ""
    found = False
    for row_name, parameter in rows:
        if row_name != name:
            continue
        if found:
            return ""
        selected = parameter
        found = True
    return selected if found else ""


if unique_parameter([("first_record", "T"), ("second_record", "U")], "second_record") != "U" or \
        unique_parameter([("duplicate", "T"), ("duplicate", "U")], "duplicate") != "":
    raise SystemExit("name-only generic extern lookup must accept unique names and reject collisions")

if FIXTURE.count("#line 0 generic-extern-owner.elisa") != 2 or not all(
    fragment in FIXTURE
    for fragment in (
        "extern first_record[T](box: mutable FirstBox[T]&, item: T) -> void",
        "extern second_record[U](box: mutable SecondBox[U]&, item: U) -> void",
        "first.first_record(3)",
        "second.second_record(4)",
    )
):
    raise SystemExit("regression must exercise two differently named generic extern owners on logical line zero")
if "generic_extern_owner_line_zero.elisa" not in SMOKE or \
        "check_generic_extern_owner_identity.py" not in SMOKE or \
        "first_record__i64" not in SMOKE or "second_record__i64" not in SMOKE:
    raise SystemExit("smoke must compile both same-line generic extern calls and run this source proof")

print("generic extern owner-offset source checks passed")
