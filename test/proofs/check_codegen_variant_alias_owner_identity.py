"""Backend variant aliases must bind only at the exact is-target position."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


structs = source("src/backend/codegen_struct_table.elisa")
producer = source("src/backend/codegen_module.elisa")
lookup = source("src/backend/codegen_env.elisa")
branching = source("src/backend/codegen_stmt_branching.elisa")
fixture = source("test/repro/try_variant_alias_owner_line_zero.elisa")

if "is_variant_alias_offsets: mutable darray[u32] = []" not in structs:
    raise SystemExit("backend variant alias index must retain target offsets")
line_push = producer.find("is_variant_alias_lines <- structs.annotations.is_variant_alias_lines.push(annotation.line)")
offset_push = producer.find("is_variant_alias_offsets <- structs.annotations.is_variant_alias_offsets.push(annotation.offset)")
name_push = producer.find("is_variant_alias_names <- structs.annotations.is_variant_alias_names.push(annotation.owner)")
if min(line_push, offset_push, name_push) < 0 or not line_push < offset_push < name_push:
    raise SystemExit("backend marker producer must keep line, offset, and alias name paired")

lookup_start = lookup.find("def is_variant_alias_at(")
lookup_end = lookup.find("\n\n", lookup_start)
lookup_body = lookup[lookup_start:lookup_end]
if "line: i64, offset: u32" not in lookup_body or \
        "is_variant_alias_lines.count != structs.annotations.is_variant_alias_offsets.count" not in lookup_body or \
        "is_variant_alias_lines.count != structs.annotations.is_variant_alias_names.count" not in lookup_body or \
        "is_variant_alias_lines[probe] == line and structs.annotations.is_variant_alias_offsets[probe] == offset" not in lookup_body:
    raise SystemExit("backend variant alias lookup must fail closed and match both target coordinates")
if "is_variant_alias_at(alias_variant_line.line, alias_variant_line.offset, structs)" not in branching:
    raise SystemExit("branch emitter must pass the target expression offset into alias lookup")

if fixture.count("#line 0 variant-alias-owner.elisa") != 2 or \
        "Choice.Pair as payload" not in fixture or "Choice.Other" not in fixture:
    raise SystemExit("same-line alias and non-alias targets must remain a backend regression case")
