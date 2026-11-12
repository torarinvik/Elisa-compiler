"""Bind view-return generic classification to the declaring function offset."""
from pathlib import Path
from proof_product_gate import read_semantic_declaration_source
import re


ROOT = Path(__file__).resolve().parents[2]
COLLECT = ROOT / "src/semantic/view_return_origins_collect.elisa"
API = ROOT / "src/semantic/view_return_origins_api.elisa"
PARSER_FUNCTIONS = ROOT / "src/parser/parser_types_function.elisa"
SMOKE = ROOT / "test/parity/owned_overload_storage_smoke.sh"
ATOM = ROOT / "test/atoms/compiler_semantic.elisa"
ATOM_SMOKE = ROOT / "test/parity/compiler_atoms_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


collection = COLLECT.read_text()
parser = PARSER_FUNCTIONS.read_text()
smoke = SMOKE.read_text()
atom = read_semantic_declaration_source(ATOM)
atom_smoke = ATOM_SMOKE.read_text()

if "declaration_pos: Ast::Pos = Ast::decl_pos(declaration)" not in parser or \
        "parameter_owner_offset == declaration_pos.offset" not in parser or \
        "parser.capture_function_generic_params(token.line, token.start, lexical_module_id)" not in parser or \
        "Ast::pos_of_token(token)" not in parser or \
        "generic_param_owner_offsets <- parser.generic_param_owner_offsets.push(function_offset) if is_generic_name" not in parser:
    raise SystemExit("function generic metadata must retain the same declaration offset stored in the AST")

generic_lookup = function_source(collection, "vro_generics_of")
if not all(fragment in generic_lookup for fragment in (
    "owner_offset: u32",
    "generic_names.count != generic_lines.count",
    "generic_names.count != generic_offsets.count",
    "generic_lines[index] == line",
    "generic_offsets[index] == owner_offset",
)):
    raise SystemExit("view-return generic lookup must validate and match the exact owner line and offset")

collector = function_source(collection, "vro_collect")
if not all(fragment in collector for fragment in (
    "generic_offsets: darray[u32]&",
    "vro_generics_of(pos.line, pos.offset, generic_lines, generic_offsets, generic_names, generics)",
    "vro_collect(body, generic_lines, generic_offsets, generic_names, view_enums, prior, prior_index, update_prior, mutables, out, scopes, pos.offset.u64() + 1.u64())",
    "vro_collect(body, generic_lines, generic_offsets, generic_names, view_enums, prior, prior_index, update_prior, mutables, out, scopes, scope)",
)):
    raise SystemExit("view-return declaration traversal must preserve owner offsets through nested scopes")

entrypoint = function_source(API.read_text(), "view_return_origin_rows")
if entrypoint.count("file.generic_param_owner_offsets") != 2:
    raise SystemExit("both view-return collection passes must receive parser-owned generic offsets")
if 'python3 "$ROOT/test/proofs/check_view_return_generic_owner_identity.py"' not in smoke:
    raise SystemExit("owned storage smoke must run the view-return generic owner proof")
if not all(fragment in atom for fragment in (
    'view_generic_names: darray[sview @source] = ["Widget"]',
    "view_generic_offsets: darray[u32] = [100]",
    "view_generic_pos: Ast::Pos = Ast::Pos{line: 0",
    "view_concrete_pos: Ast::Pos = Ast::Pos{line: 0",
    "vro_generics_of(view_generic_pos.line, view_generic_pos.offset,",
    "vro_generics_of(view_concrete_pos.line, view_concrete_pos.offset,",
    'return 103 if not vro_borrow_return(Ast::Expr.Ident("Widget", view_generic_pos), generic_parameters)',
    'return 103 if vro_borrow_return(Ast::Expr.Ident("Widget", view_concrete_pos), concrete_parameters)',
)) or "  semantic " not in atom_smoke or \
        'python3 "$ROOT/test/proofs/check_view_return_generic_owner_identity.py"' not in atom_smoke:
    raise SystemExit("semantic compiler atom must reject a same-line generic-to-concrete return leak")
