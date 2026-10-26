"""Extern return metadata must join to the exact declaration token."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_export_surface.elisa").read_text()
RETURN_TEXT = (ROOT / "src/parser/parser_extern_return_text.elisa").read_text()
BORROW_CHECKER = (ROOT / "src/semantic/check_unknown_function_annotation.elisa").read_text()
WRAPPER_CHECKER = (ROOT / "src/semantic/check_errorset_wrapper_return.elisa").read_text()
BORROW_AFTER_MOVE = (ROOT / "src/semantic/check_borrow_after_move/store_ref_links.elisa").read_text()
TRY_CHECKER = (ROOT / "src/semantic/check_try_fallible/using_aliases.elisa").read_text()
FIXTURE = (ROOT / "test/repro/extern_return_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/function_annotation_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


producer = function_source(PARSER, "parse_extern_signature_and_body")
text_recorder = function_source(RETURN_TEXT, "record_extern_return_text")
return_lookup = function_source(BORROW_CHECKER, "extern_return_type_at")
borrow_checker = function_source(BORROW_CHECKER, "check_extern_borrow_annotation")
declaration_checker = function_source(BORROW_CHECKER, "check_unknown_function_annotation_declarations")
infallible_checker = function_source(WRAPPER_CHECKER, "ewr_extern_return_is_known_infallible")
try_alias_checker = function_source(TRY_CHECKER, "try_noncall_callable_error_family")
extern_lender_collector = function_source(BORROW_AFTER_MOVE, "bam_collect_extern_lenders")

extern_return_row = re.search(
    r'Ast::EnumAnnotation\{owner: "__extern_return", name: extern_return_type, line: token\.line, offset: token\.start\}',
    producer,
)
if extern_return_row is None:
    raise SystemExit("extern return type metadata must use the owning extern token position")
if "parser.record_extern_return_text(name, token.line, token.start)" not in producer:
    raise SystemExit("extern return spelling recorder must receive the declaration token offset")
if 'owner: "__extern_return_ptr"' not in producer or \
        "name: name, line: token.line, offset: token.start" not in producer or \
        'annotation.owner == "__extern_return_ptr"' not in extern_lender_collector or \
        "annotation.name == name" not in extern_lender_collector or \
        "annotation.line == line.line and annotation.offset == line.offset" not in extern_lender_collector or \
        "line.offset == 0" in extern_lender_collector:
    raise SystemExit("extern lender discovery must join pointer-return metadata to its exact declaration token, including offset zero")
if "owner_offset: u32" not in text_recorder or not all(
    fragment in text_recorder for fragment in (
        'name: "__extern_return_text_complete", line: line, offset: owner_offset',
        'name: spelling, line: line, offset: owner_offset',
    )
):
    raise SystemExit("both extern return spelling rows must retain their exact owner offset")

if "owner_offset: u32" not in return_lookup or \
        "annotation.line == line and annotation.offset == owner_offset" not in return_lookup:
    raise SystemExit("extern return type lookup must use both logical line and owner offset")
if "extern_return_type_at(enum_annotations, line, owner_offset)" not in borrow_checker or \
        "line.line, line.offset, table" not in declaration_checker:
    raise SystemExit("extern borrow checking must pass the exact declaration offset through the lookup")

for fragment in (
    "row.line == extern_line and row.offset == extern_offset",
    'row.name == "__extern_return_text_complete" and row.line == extern_line and row.offset == extern_offset',
    'row.owner == "__extern_return_text" and row.line == extern_line and row.offset == extern_offset',
    'row.owner == "__extern_return" and row.line == extern_line and row.offset == extern_offset',
):
    if fragment not in infallible_checker:
        raise SystemExit("infallible extern return fallback must match all metadata by exact owner position")
if "annotation.line == marker.line and annotation.offset == marker.offset" not in try_alias_checker or \
        'annotation.name == "__extern_return_text_complete"' not in try_alias_checker or \
        'annotation.name == "__export_fn"' not in try_alias_checker:
    raise SystemExit("try alias metadata fallback must pair exported/extern completion markers by exact position")
if 'Ast::EnumAnnotation{owner: name, name: "__export_fn", line: token.line, offset: token.start}' not in producer:
    raise SystemExit("export function marker used by the try fallback must retain its source token offset")

if FIXTURE.count("#line 0 extern-return-owner.elisa") != 2 or not all(
    fragment in FIXTURE for fragment in (
        "extern first() -> First",
        "@borrows_return(field, second, value)",
        "extern second(value: i64&) -> Second",
    )
):
    raise SystemExit("fixture must collide two extern return types on logical line zero")
if "extern_return_owner_line_zero.elisa" not in SMOKE or \
        'references unknown return field path "second" in First' not in SMOKE or \
        'requires a concrete struct return type, got' not in SMOKE:
    raise SystemExit("function annotation smoke must reject stale or missing return-type pairings")

print("extern return owner-offset source checks passed")
