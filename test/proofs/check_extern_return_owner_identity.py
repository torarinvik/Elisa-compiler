"""Extern return annotations must resolve to the exact declaration owner."""
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


fallback = source("src/semantic/check_try_fallible/fallback_casts.elisa")
backend_helpers = source("src/backend/codegen_declare_extern.elisa")
backend_debug = source("src/backend/codegen_debug.elisa")
backend_body = source("src/backend/codegen_declare_extern_body.elisa")
extern_bounds_parser = source("src/parser/parser_extern_bounds.elisa")

declaration = function_text(fallback, "try_fallback_extern_declaration_line")
if (
    "offset: u32" not in declaration
    or declaration.count("symbol.offset") < 2
    or declaration.count("function_count == 1.usize()") < 2
    or "return (false, 0, 0)" not in declaration
):
    raise SystemExit("try-fallback extern lookup must return an offset only for a unique same-name function")
return_info = function_text(fallback, "try_fallback_extern_return_info")
if "declaration.offset" not in return_info or return_info.count("annotation.offset == declaration_offset") < 4:
    raise SystemExit("try-fallback return head, darray element, ptr, and optional rows need exact owner offsets")

for helper in ("extern_return_is_pointer", "extern_return_is_optional"):
    body = function_text(backend_helpers, helper)
    if "extern_offset: u32" not in body or "annotations[row.usize()].offset == extern_offset" not in body:
        raise SystemExit(f"{helper} must select the marker for the exact extern declaration")

optional = function_text(backend_helpers, "extern_return_optional_at_line")
if "offset: u32" not in optional or "annotations[row.usize()].line == line and annotations[row.usize()].offset == offset" not in optional:
    raise SystemExit("resource optional-return lookup must match both declaration line and offset")
resource = function_text(backend_helpers, "extern_resource_return_kind")
if "line: u32, offset: u32" not in resource or "extern_return_optional_at_line(annotations, extern_name, line, offset)" not in resource:
    raise SystemExit("resource return classification must carry the declaration identity")
darray = function_text(backend_helpers, "extern_return_darray_element_of")
if "line: u32, offset: u32" not in darray or "annotation.line == line and annotation.offset == offset" not in darray:
    raise SystemExit("extern darray element lookup must select the exact declaration row")

if backend_debug.count("Ast::decl_pos(nested).offset") != 1 or backend_debug.count("Ast::decl_pos(declaration).offset") != 1:
    raise SystemExit("both top-level and module extern lowering must pass their AST declaration offset")
if "extern_return_darray_element_of(annotations, extern_line.line, extern_line.offset)" not in backend_body:
    raise SystemExit("darray return lowering must pass the exact extern source position")
if "extern_return_is_optional(annotations, extern_name, extern_line.offset)" not in backend_body:
    raise SystemExit("optional resource return lowering must pass the exact extern offset")
if "extern_resource_return_kind(structs, annotations, extern_name, return_type_name, extern_line.line, extern_line.offset)" not in backend_body:
    raise SystemExit("resource return classification must receive line and offset")
# The nullable FnTable flag was already an exact-offset lookup; preserve that path.
if 'annotation_pair_present(structs, annotations, "__extern_return_optional", extern_name, extern_line.offset)' not in backend_body:
    raise SystemExit("FnTable nullable return metadata must retain its exact-offset lookup")

if 'plan_annotation.offset == extern_line.offset' not in backend_body:
    raise SystemExit("extern @bounds C-part plans must be filtered by their declaration offset")
if 'name: "__bounds_cpart", line: code, offset: extern_offset' not in extern_bounds_parser:
    raise SystemExit("extern @bounds C-part metadata must carry the declaration offset")

extern_parser = source("src/parser/parser_export_surface.elisa")
for row in (
    'owner: "__extern_return", name: extern_return_type, line: token.line, offset: token.start',
    'owner: "__extern_return_ptr", name: name, line: token.line, offset: token.start',
    'owner: "__extern_return_optional", name: name, line: token.line, offset: token.start',
    'name: "__extern_return_darray_elem", line: token.line, offset: token.start',
):
    if row not in extern_parser:
        raise SystemExit(f"extern return metadata must carry its declaration offset: {row}")
