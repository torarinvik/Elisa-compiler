"""Bind protocol precondition generic receivers to exact function owners."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_protocol_precondition_unproven.elisa"
PARSER = ROOT / "src/parser/parser_types_function.elisa"
FIXTURE = ROOT / "test/repro/protocol_precondition_generic_owner.elisa"
SMOKE = ROOT / "test/parity/protocol_precondition_generic_owner_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
parser = PARSER.read_text()
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()

signature_lookup = function_source(source, "ppu_has_signature_requires")
if not all(fragment in signature_lookup for fragment in (
    'annotation.owner == "__signature_contract"',
    'annotation.name == "requires"',
    "annotation.line == decl_line",
    "annotation.offset == decl_offset",
)):
    raise SystemExit("signature facts must match the exact function declaration owner")

signature_drain = function_source(parser, "drain_signature_contracts")
if not all(fragment in signature_drain for fragment in (
    "function_offset: u32",
    'owner: "__signature_contract"',
    "line: function_line",
    "offset: function_offset",
)) or "drain_signature_contracts(token.line, token.start)" not in parser:
    raise SystemExit("parser must preserve the owning function offset for each signature contract")
if "Ast::Decl.Func(function_name, threaded_params, return_type, resolved_body, effects, decorators, Ast::pos_of_token(token))" not in parser:
    raise SystemExit("signature-contract owner offset must match the parsed function declaration position")

generic_test = function_source(source, "ppu_is_generic_param")
if not all(fragment in generic_test for fragment in (
    "decl_line: u32, decl_offset: u32",
    "generic_names.count != generic_lines.count",
    "generic_names.count != generic_offsets.count",
    "generic_lines[probe] < 2147483648",
    "generic_lines[probe] == decl_line",
    "generic_offsets[probe] == decl_offset",
    "generic_names[probe] == name",
)):
    raise SystemExit("protocol precondition generic lookup must match a valid exact (line, offset, name) row")

receiver_collection = function_source(source, "ppu_collect_generic_receivers")
if not all(fragment in receiver_collection for fragment in (
    "decl_offset: u32",
    "generic_names.count != generic_lines.count",
    "generic_names.count != generic_offsets.count",
    "generic_offsets",
    "ppu_is_generic_param(type_name, decl_line, decl_offset, generic_names, generic_lines, generic_offsets)",
)):
    raise SystemExit("receiver collection must validate and forward all parallel generic-owner metadata")

declaration_walk = function_source(source, "ppu_check_declarations")
if not all(fragment in declaration_walk for fragment in (
    "generic_offsets: darray[u32]&",
    "line.offset",
    "line.line, line.offset, generic_names, generic_lines, generic_offsets, receivers",
    "ppu_has_signature_requires(line.line, line.offset, annotations)",
    "module_body, methods, annotations, generic_names, generic_lines, generic_offsets, table",
    "scoped_body, methods, annotations, generic_names, generic_lines, generic_offsets, table",
)):
    raise SystemExit("declaration traversal must carry generic owner offsets into nested declarations")
if "file.generic_param_owner_offsets" not in source:
    raise SystemExit("entrypoint must provide parser-owned generic parameter owner offsets")
if "file.enum_annotations, file.generic_param_names, file.generic_param_lines, file.generic_param_owner_offsets, table" not in source:
    raise SystemExit("entrypoint must pass exact signature-contract owner markers into declaration checks")

if fixture.count("#line 37 ") != 3 or fixture.count("#line 0 ") != 2 or \
        "def unrelated[C: Counted](value: C)" not in fixture or \
        "return value.check()" not in fixture or \
        "def has_requirement(value: i64) -> i64 requires value > 0:" not in fixture or \
        "def concrete(value: C)" not in fixture or \
        "def unrelated_zero[C](value: C)" not in fixture or \
        "def concrete_zero(value: C)" not in fixture or \
        "def generic_call[Q: Counted](value: Q)" not in fixture or \
        "requires self.count() > 0" not in fixture:
    raise SystemExit("regression fixture must contrast same-line concrete and generic receiver owners, including line zero")

if 'python3 "$REPO_ROOT/test/proofs/check_protocol_precondition_generic_owner.py"' not in smoke or \
        "'could not be proven statically at this call'" not in smoke or \
        "'  L38 precondition of \"check\"'" not in smoke or \
        "'  L71 precondition of \"check\"'" not in smoke:
    raise SystemExit("protocol precondition smoke must run the source proof and pin the real generic warning")
