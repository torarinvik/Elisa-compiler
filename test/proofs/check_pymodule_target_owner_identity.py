"""Python-module export target rows must pair by their exact export-name token."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_export_surface.elisa").read_text()
WILDCARDS = (ROOT / "src/driver/pymodule/export_names.elisa").read_text()
FIXTURE = (ROOT / "test/repro/pymodule_target_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/pymodule_qualified_targets_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^(?:        )?def {re.escape(name)}\(.*?(?=^(?:        )?def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


producer = function_source(PARSER, "capture_export_pymodule_body")
wildcard = function_source(WILDCARDS, "pymodule_expand_wildcard_exports")
for marker in (
    "__pymodule_fn",
    "__pymodule_target_ref",
    "__pymodule_const",
    "__pymodule_const_target_ref",
):
    rows = re.findall(rf'Ast::EnumAnnotation\{{[^}}]*name: "{re.escape(marker)}"[^}}]*\}}', producer)
    if len(rows) != 1 or not all(fragment in rows[0] for fragment in (
        "line: line",
        "offset: public_token.start",
    )):
        raise SystemExit(f"explicit {marker} row must share the public-name token position")
if not all(fragment in wildcard for fragment in (
    "line: wildcard_function_pos.line, offset: wildcard_function_pos.offset",
    "line: wildcard_const_pos.line, offset: wildcard_const_pos.offset",
)):
    raise SystemExit("wildcard-expanded target pairs must retain their declaration offsets")

checked_joins = 0
for path in (ROOT / "src").rglob("*.elisa"):
    for line in path.read_text().splitlines():
        if ("__pymodule_target_ref" in line or "__pymodule_const_target_ref" in line) and ".line ==" in line:
            if ".offset ==" not in line:
                raise SystemExit(f"Python-module target join still uses logical line only: {path}: {line.strip()}")
            checked_joins += 1
if checked_joins < 10:
    raise SystemExit("expected to source-check all Python-module target consumers")

if FIXTURE.count("#line 0 pymodule-target-owner.elisa") != 4 or not all(
    fragment in FIXTURE for fragment in (
        "fn first_fn = Left::first",
        "fn second_fn = Right::second",
        "const first_constant = Left::FIRST",
        "const second_constant = Right::SECOND",
    )
):
    raise SystemExit("fixture must collide function and constant target rows on one logical line")
if "pymodule_target_owner_line_zero.elisa" not in SMOKE or \
        '"first_fn": "Left::first"' not in SMOKE or \
        '"second_fn": "Right::second"' not in SMOKE or \
        "target_owner_line_zero.first_fn() == 11" not in SMOKE:
    raise SystemExit("qualified-target smoke must assert exact manifest and runtime target selection")

print("pymodule target owner-offset source checks passed")
