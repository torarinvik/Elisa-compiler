"""Extern resource annotations must pair with their exact synthetic extern declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_export_surface.elisa").read_text()
CHECKER = (ROOT / "src/semantic/check_extern_resource.elisa").read_text()
FIXTURE = (ROOT / "test/repro/extern_resource_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/extern_resource_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


producer = function_source(PARSER, "parse_extern_signature_and_body")
checker = function_source(CHECKER, "check_extern_resource")
row = re.search(r'Ast::EnumAnnotation\{owner: resource_name, name: "__extern_resource"[^}]*\}', producer)
if row is None or not all(fragment in row.group(0) for fragment in (
    "line: token.line",
    "offset: token.start",
)):
    raise SystemExit("extern resource row must use the synthetic extern declaration token position")
if 'annotation.line == line.line and annotation.offset == line.offset' not in checker:
    raise SystemExit("missing-drop validation must match the exact non-callable extern declaration")
if FIXTURE.count("#line 0 extern-resource-owner.elisa") != 2 or \
        "extern resource ExistingDrop" not in FIXTURE or \
        "extern resource MissingDrop" not in FIXTURE or \
        "def __drop__(self: ExistingDrop)" not in FIXTURE:
    raise SystemExit("fixture must pair a valid resource and a missing-drop resource on one logical line")
if "extern_resource_owner_line_zero.elisa" not in SMOKE or \
        'extern resource "MissingDrop" declares no `__drop__`' not in SMOKE:
    raise SystemExit("extern resource smoke must require one missing-drop diagnostic for the exact resource")

print("extern resource owner-offset source checks passed")
