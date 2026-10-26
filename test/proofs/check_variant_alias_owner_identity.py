"""Variant-alias bindings must belong to the exact `is` RHS field."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text()


parser = read("src/parser/parser_expr_binary.elisa")
types = read("src/semantic/semantic_types_symbol_table.elisa")
collector = read("src/semantic/semantic_api/table_setup.elisa")
resolver = read("src/semantic/resolve_scope/pattern_binders.elisa")
flow = read("src/semantic/resolve_flow.elisa")
authority = read("src/semantic/check_global_authority/gather_targets.elisa")
fixture = read("test/repro/variant_alias_owner_line_zero.elisa")
smoke = read("test/parity/variant_alias_owner_line_zero_smoke.sh")

if 'owner: alias_name, name: "__is_variant_alias", line: alias_target_line.line, offset: alias_target_line.offset' not in parser:
    raise SystemExit("parser alias rows must retain the RHS field's exact position")
if "is_variant_alias_offsets: mutable darray[u32] = []" not in types or \
        "is_variant_alias_offsets <- table.is_variant_alias_offsets.push(annotation.offset)" not in collector:
    raise SystemExit("semantic symbol collection must preserve alias offsets")
if "alias_offsets: darray[u32]&" not in resolver or \
        "alias_offsets[probe] == alias_variant_line.offset" not in resolver or \
        "table.is_variant_alias_offsets" not in flow:
    raise SystemExit("scope resolution must select only the alias attached to this RHS field")
if "table.is_variant_alias_lines.count == table.is_variant_alias_offsets.count and table.is_variant_alias_lines.count == table.is_variant_alias_names.count" not in authority or \
        "table.is_variant_alias_offsets[probe] == alias_variant_line.offset" not in authority:
    raise SystemExit("GlobalAuthority condition binding must match line and offset")
if fixture.count("#line 0 variant-alias-owner.elisa") != 2 or \
        "Some as pulse" not in fixture or "Empty as other" not in fixture or "pulse <- 1" not in fixture:
    raise SystemExit("regression must prevent a sibling same-line alias from shadowing the global write")
if "variant_alias_owner_line_zero.elisa" not in smoke or \
        "accesses a global mutable binding without Global.Write" not in smoke:
    raise SystemExit("smoke must require Global.Write for the unshadowed global")
