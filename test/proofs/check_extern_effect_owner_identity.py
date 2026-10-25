"""Extern capability rows must resolve to the declaration that produced them."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text()


def function_text(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        text,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


parser = source("src/parser/parser_export_surface.elisa")
checker = source("src/semantic/check_ungranted_panic.elisa")
grant_checker = source("src/semantic/check_ungranted_panic_grants.elisa")
coverage_checker = source("src/semantic/check_ungranted_panic_coverage.elisa")
gate = source("test/parity/diagnostics_smoke.sh")
collision_fixture = source("test/repro/extern_cross_module_effect_leaf_collision.elisa")

for row in (
    'owner: name, name: "__extern_effect", line: token.line, offset: token.start',
    'owner: "__extern_effect_ref", name: extern_effect_ref, line: token.line, offset: token.start',
    'owner: name, name: "__extern_segment_owner", line: token.line, offset: token.start',
):
    if row not in parser:
        raise SystemExit(f"extern declaration metadata must carry token.start: {row}")

if 'owner: name, name: "__extern_effect_blocking", line: token.line, offset: token.start' not in parser:
    raise SystemExit("@blocking must have a distinct exact-owner effect marker")

effect_ref = function_text(checker, "extern_effect_ref_at")
if 'annotations[probe].owner == "__extern_effect_ref"' not in effect_ref or "annotations[probe].line == line and annotations[probe].offset == offset" not in effect_ref:
    raise SystemExit("extern capability ref lookup must match the exact declaration position")
if "extern_effect_ref_on_line" in checker:
    raise SystemExit("extern capability refs must not be selected by logical line alone")

collector = function_text(checker, "collect_extern_effects")
if not all(fragment in collector for fragment in (
    'annotation.name == "__extern_effect" or annotation.name == "__extern_effect_blocking"',
    '"Blocking.RawExtern" if annotation.name == "__extern_effect_blocking"',
    "extern_effect_ref_at(annotations, annotation.line, annotation.offset)",
)):
    raise SystemExit("extern effect collection must pair signature refs by offset and keep blocking distinct")

module_collision_guard = function_text(grant_checker, "effect_name_has_multiple_module_owners")
if not all(fragment in module_collision_guard for fragment in (
    "symbol_chain_head(table, name)",
    "symbol.kind == SymbolKind.Func",
    "first_module <- symbol.module_owner",
    "symbol.module_owner != first_module",
)):
    raise SystemExit("bare-name effect lookups must detect a same-leaf declaration from another module")

postfix_checker = function_text(grant_checker, "check_ungranted_panic_statements")
if "effect_name_has_multiple_module_owners(table, grant_callee)" not in postfix_checker or \
        "not ambiguous_module_owner" not in postfix_checker:
    raise SystemExit("postfix-grant coverage must fail closed when a bare callee leaf spans modules")

block_checker = function_text(coverage_checker, "cov_check_call")
block_guard = block_checker.find("effect_name_has_multiple_module_owners(table, callee)")
block_lookup = block_checker.find("cov_call_uncovered_ref(table, coverage_annotations, callee, granted)")
if block_guard < 0 or block_lookup < 0 or block_guard >= block_lookup:
    raise SystemExit("block-grant coverage must reject cross-module bare-name effect rows before lookup")

if not all(fragment in collision_fixture for fragment in (
    "module First:",
    "extern inspect() -> void can[Disk.Read]",
    "module Second:",
    "extern inspect() -> void can[Console.Write]",
    "Second::inspect()",
    "Second::inspect() can Console.Write",
)):
    raise SystemExit("same-leaf module fixture must cover block and postfix grants against distinct extern rows")

if 'python3 "$REPO_ROOT/test/proofs/check_extern_effect_owner_identity.py"' not in gate:
    raise SystemExit("diagnostics gate must run the extern effect owner proof")
