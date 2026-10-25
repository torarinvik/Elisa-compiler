"""Bind projected generic storage regions to the exact struct declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION = ROOT / "src/semantic/region_escape_stores.elisa"
FIXTURE = ROOT / "test/repro/region_escape_generic_owner_line_collision.elisa"
SMOKE = ROOT / "test/parity/region_escape_generic_owner_line_collision_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


implementation = IMPLEMENTATION.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
receiver_region = function_source(implementation, "region_escape_receiver_storage_region")
owner_identity = function_source(implementation, "region_escape_struct_identity")

if not all(fragment in receiver_region for fragment in (
    "struct_identity: (found: bool, line: u32, offset: u32)",
    "region_escape_struct_identity(owner, field_info.module, table)",
    "not struct_identity.found",
    "table.generic_param_lines.count != table.generic_param_names.count",
    "table.generic_param_lines.count != table.generic_param_owner_offsets.count",
    "table.generic_param_lines[row] == struct_identity.line",
    "table.generic_param_owner_offsets[row] == struct_identity.offset",
    "region_escape_region_binding_id(field_region, struct_identity.line, table)",
)):
    raise SystemExit("projected generic storage parameters must join by exact struct line and offset")
if not all(fragment in owner_identity for fragment in (
    "-> (found: bool, line: u32, offset: u32)",
    "symbol.module_owner == module",
    "selected_line <- symbol.line",
    "selected_offset <- symbol.offset",
    "matching_structs != 1 or same_name_structs != 1",
    "return (true, selected_line, selected_offset)",
)) or "same_line_owners" in owner_identity:
    raise SystemExit("struct lookup must preserve its declaration offset without rejecting unrelated same-line owners")

if fixture.count("#line 0 ") != 2 or not all(fragment in fixture for fragment in (
    "#line 0 region-buffer-owner.elisa\nstruct RegionBuffer[@r]",
    "#line 0 sibling-generic-owner.elisa\nstruct OtherGeneric[@s]",
    "views: mutable darray[sview @r] @r",
    "buffer: RegionBuffer[scratch] = RegionBuffer{views: []}",
    "buffer.views.push(source.as_sview())",
)):
    raise SystemExit("fixture must collide two generic struct display lines and grow the exact owner's projected container")
if "region_escape_generic_owner_line_collision.elisa" not in smoke or \
        "expected no region diagnostics" not in smoke:
    raise SystemExit("smoke must compile the same-line generic-owner fixture and require a clean result")
print("region escape generic owner source proof OK")
