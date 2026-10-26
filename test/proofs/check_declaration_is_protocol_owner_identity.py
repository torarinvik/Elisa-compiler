"""Protocol duplicate categories must belong to the exact protocol declaration."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_decl_named_block.elisa").read_text()
CHECKER = (ROOT / "src/semantic/symbols_duplicates.elisa").read_text()
FIXTURE = (ROOT / "test/repro/protocol_duplicate_category_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/protocol_duplicate_category_owner_line_zero_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*def {re.escape(name)}\(.*?(?=^\s*def |^\s*public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


named_block = function_source(PARSER, "named_block_declaration")
protocol_identity = function_source(CHECKER, "declaration_is_protocol")
if 'owner: "__protocol_decl"' not in named_block or "offset: token.start" not in named_block:
    raise SystemExit("protocol declaration markers must retain the declaration token offset")
if "annotation.line == line.line" not in protocol_identity or \
        "annotation.offset == line.offset" not in protocol_identity:
    raise SystemExit("protocol category lookup must match the exact Alias declaration position")
if FIXTURE.count("#line 0 protocol-category-owner.elisa") != 5 or \
        "module Protocols:" not in FIXTURE or "module Types:" not in FIXTURE or \
        FIXTURE.count("type Shared =") != 2 or \
        FIXTURE.count("#line 0 protocol-category-owner.elisa\n    protocol Shared:") != 1 or \
        FIXTURE.count("#line 0 protocol-category-owner.elisa\n    type Shared =") != 2:
    raise SystemExit("regression must collide logical line zero across modules with repeated type aliases")
if "protocol_duplicate_category_owner_line_zero.elisa" not in SMOKE or \
        'duplicate type "Shared"' not in SMOKE or \
        'duplicate interface "Shared"' not in SMOKE:
    raise SystemExit("smoke must assert the duplicate type category and reject protocol misclassification")

print("protocol duplicate-category declaration-identity source proof OK")
