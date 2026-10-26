"""Variant alias bindings in try analysis must belong to the exact is-target expression."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_expr_binary.elisa").read_text()
CONSUMER = (ROOT / "src/semantic/check_try_fallible/block_sources.elisa").read_text()
FIXTURE = (ROOT / "test/repro/try_variant_alias_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/try_fallible_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


producer = function_source(PARSER, "binary_expression_step")
consumer = function_source(CONSUMER, "try_noncall_variant_alias_binds_name")
row = re.search(r'Ast::EnumAnnotation\{owner: alias_name, name: "__is_variant_alias"[^}]*\}', producer)
if row is None or not all(fragment in row.group(0) for fragment in (
    "line: alias_target_line.line",
    "offset: alias_target_line.offset",
)):
    raise SystemExit("variant alias metadata must use the exact is-target field position")
if not all(fragment in consumer for fragment in (
    "annotation.owner == candidate",
    'annotation.name == "__is_variant_alias"',
    "annotation.line == variant_line.line",
    "annotation.offset == variant_line.offset",
)):
    raise SystemExit("variant alias binding lookup must match both coordinates of its target expression")
if FIXTURE.count("#line 0 variant-alias-owner.elisa") != 2 or not all(
    fragment in FIXTURE for fragment in (
        "Choice.Pair as payload",
        "Choice.Other",
        "return try payload",
        "error[OriginFault]",
        "error[CallerFault]",
    )
):
    raise SystemExit("collision fixture must pair one alias test with a same-line non-alias test and a fallible outer value")
if "try_variant_alias_owner_line_zero.elisa" not in SMOKE or \
        "cannot propagate OriginFault from a function returning CallerFault" not in SMOKE:
    raise SystemExit("try smoke must require the outer payload's propagation mismatch")

print("try variant alias owner-offset source checks passed")
