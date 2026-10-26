"""Region strategy rows must belong to the exact region statement."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_stmt_contextual.elisa").read_text()
CHECKER = (ROOT / "src/semantic/check_region_backing.elisa").read_text()
FIXTURE = (ROOT / "test/repro/region_strategy_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/region_scope_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


producer = function_source(PARSER, "contextual_statement")
lookup = function_source(CHECKER, "region_strategy_unknown_at")
checker = function_source(CHECKER, "check_region_backing_statements")
row = re.search(r'Ast::EnumAnnotation\{owner: Lexer::text_or_empty\(strategy_token,[^}]*\}', producer)
if row is None or not all(fragment in row.group(0) for fragment in (
    'name: "__region_strategy"',
    "line: token.line",
    "offset: token.start",
)):
    raise SystemExit("region strategy row must use the region statement token line and offset")
if "owner_offset: u32" not in lookup or not all(fragment in lookup for fragment in (
    'annotation.name == "__region_strategy"',
    "annotation.line == line and annotation.offset == owner_offset",
    "not RegionBackingKnown::is_known(annotation.owner)",
    "found <- annotation.owner",
)):
    raise SystemExit("region strategy lookup must match its exact statement owner")
if "region_strategy_unknown_at(annotations, line.line, line.offset, &unknown_strategy)" not in checker:
    raise SystemExit("region strategy checker must pass the statement Pos offset")
if FIXTURE.count("#line 0 region-strategy-owner.elisa") != 3 or not all(
    fragment in FIXTURE for fragment in (
        "using bogus_first",
        "using fixed",
        "using bogus_last",
    )
):
    raise SystemExit("collision fixture must place distinct invalid and valid strategies on one logical line")
if "region_strategy_owner_line_zero.elisa" not in SMOKE or \
        'unknown region backing "bogus_first"' not in SMOKE or \
        'unknown region backing "bogus_last"' not in SMOKE or \
        'unknown region backing "fixed"' not in SMOKE:
    raise SystemExit("region smoke must check both exact-owner diagnostics")

print("region strategy owner-offset source checks passed")
