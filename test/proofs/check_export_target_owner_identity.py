"""Function export targets must be joined to the owning declaration token."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_export_surface.elisa").read_text()
ALIASES = (ROOT / "src/backend/codegen_export_aliases.elisa").read_text()
EXTERN_BODY = (ROOT / "src/backend/codegen_declare_extern_body.elisa").read_text()
CODEGEN_DEBUG = (ROOT / "src/backend/codegen_debug.elisa").read_text()
C_HEADER = (ROOT / "src/backend/c_header.elisa").read_text()
C_HEADER_REACHABLE = (ROOT / "src/backend/c_header_reachable.elisa").read_text()
UNSAFE_EXTERNS = (ROOT / "src/driver/elisac_emit_unsafe_externs.elisa").read_text()
UNSAFE_REPORT = (ROOT / "src/driver/elisac_emit_unsafe_report.elisa").read_text()
UNSAFE_SEGMENTS = (ROOT / "src/driver/elisac_emit_unsafe_report_segments.elisa").read_text()
AST_DECL = (ROOT / "src/driver/elisac_emit_ast_decl.elisa").read_text()
WASM = (ROOT / "src/driver/emit_wasm_exports.elisa").read_text()
AST_TESTS = (ROOT / "test/parity/parser_ast_decls.elisa").read_text()
FIXTURE_PATH = ROOT / "test/repro/export_target_owner_line_zero.elisa"
FIXTURE = FIXTURE_PATH.read_text()
SMOKE_PATH = ROOT / "test/parity/export_target_owner_line_zero_smoke.sh"
SMOKE = SMOKE_PATH.read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^\s*def {re.escape(name)}\(.*?(?=^\s*def |^\s*public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


parser = compact(PARSER)
target_recorder = compact(function_source(PARSER, "record_export_reexport_target"))
generic_recorder = compact(function_source(PARSER, "record_export_reexport_generic_if"))
capture = compact(function_source(PARSER, "capture_export_reexport_target"))
reference_lookup = compact(function_source(ALIASES, "export_target_ref_at_position"))
target_lookup = compact(function_source(ALIASES, "export_target_of_indexed"))
ast_target_lookup = compact(function_source(AST_DECL, "emit_ast_export_fn_target"))

if 'Ast::EnumAnnotation{owner:name,name:"__export_fn",line:token.line,offset:token.start}' not in parser:
    raise SystemExit("export declaration marker must retain the declaration token offset")
if "capture_export_reexport_target(name,token.line,token.start)" not in parser:
    raise SystemExit("re-export target capture must receive the declaration token offset")
if "owner_offset:u32" not in target_recorder or not all(
    fragment in target_recorder
    for fragment in (
        'owner:export_name,name:target_name,line:line,offset:owner_offset',
        'owner:target_name,name:"__export_target_ref",line:line,offset:owner_offset',
    )
):
    raise SystemExit("re-export target and target-reference rows must share exact owner identity")
if "owner_offset:u32" not in generic_recorder or "line:3900000060,offset:owner_offset" not in generic_recorder:
    raise SystemExit("generic re-export argument metadata must retain its declaration offset")
if "record_export_reexport_target(export_name,target_name,line,owner_offset)" not in capture or \
        "record_export_reexport_generic_if(export_name,target_name,line,owner_offset,generic_argument,has_generic_argument)" not in capture:
    raise SystemExit("captured re-export metadata must consistently thread the declaration offset")

if "annotation.line==lineandannotation.offset==owner_offset" not in reference_lookup:
    raise SystemExit("target-reference lookup must match both logical line and declaration offset")
if "export_line:u32,export_offset:u32" not in target_lookup or \
        "annotation.line==export_lineandannotation.offset==export_offset" not in target_lookup or \
        "found_export:mutablebool=false" not in target_lookup or \
        'return""ifnotfound_export' not in target_lookup:
    raise SystemExit("indexed export lookup must use exact position and an explicit found flag")
if "export_line==0" in target_lookup:
    raise SystemExit("logical line zero must not be used as the missing-export sentinel")
if "annotation.offset==export_offset" not in target_lookup or \
        "export_target_ref_at_position(structs,annotations,annotation.name,export_line,export_offset)" not in target_lookup:
    raise SystemExit("target rows and target-reference rows must be paired at the exact export position")

if "export_target_of_indexed(structs,annotations,extern_name,extern_line.line,extern_line.offset)" not in compact(EXTERN_BODY):
    raise SystemExit("extern declaration codegen must pass the declaration position")
debug = compact(CODEGEN_DEBUG)
if "export_target_of_indexed(structs,file.enum_annotations,export_name,export_pos.line,export_pos.offset)" not in debug or \
        "generic_annotation.offset==export_pos.offset" not in debug:
    raise SystemExit("wrapper emission must select target and generic argument by declaration offset")

if "annotation.offset==owner_offset" not in ast_target_lookup or \
        "emit_ast_export_fn_target(ex_rows,ast_ex_name,ast_ex_line.line,ast_ex_line.offset)" not in compact(AST_DECL):
    raise SystemExit("AST declaration emission must select the exact export owner")
if "emit_ast_export_fn_target(file.enum_annotations,ex_name,ex_line.line,ex_line.offset)" not in compact(WASM):
    raise SystemExit("WASM export discovery must select the exact export owner")
for source, label in ((C_HEADER, "C header generation"), (C_HEADER_REACHABLE, "C header reachability")):
    if "annotation.offset==line.offset" not in compact(source):
        raise SystemExit(f"{label} must match the export marker to the declaration position")

unsafe = compact(UNSAFE_EXTERNS)
if "unsafe_export_marker_matches(markers: darray[Ast::EnumAnnotation]&" not in unsafe or \
        'marker.owner==wantedandmarker.name=="__export_fn"andmarker.line==lineandmarker.offset==offset' not in unsafe:
    raise SystemExit("unsafe extern reporting must represent export declarations by exact owner position")
if "unsafe_export_marker_matches(export_markers,name,line.line,line.offset)" not in unsafe or \
        "unsafe_export_marker_matches(export_markers,us_x_name,us_x_line.line,us_x_line.offset)" not in compact(UNSAFE_REPORT) or \
        "export_markers:mutabledarray[Ast::EnumAnnotation]=[]" not in compact(UNSAFE_SEGMENTS):
    raise SystemExit("declaration-scoped unsafe-report filters must match export marker offsets")
unsafe_collect = compact(function_source(UNSAFE_REPORT, "unsafe_collect_declarations"))
if unsafe_collect.index("name_cursor<-name_cursor+1.usize()") > unsafe_collect.index(
    "unsafe_export_marker_matches(export_markers,us_x_name,us_x_line.line,us_x_line.offset)"
):
    raise SystemExit("unsafe export filtering must preserve the declaration-name cursor before skipping exports")

for path in (ROOT / "src").rglob("*.elisa"):
    for source_line in path.read_text().splitlines():
        if "export_target_of_indexed(" in source_line and "def export_target_of_indexed" not in source_line:
            if ".line" not in source_line or ".offset" not in source_line:
                raise SystemExit(f"export target consumer lacks declaration position: {path}: {source_line.strip()}")
        if "emit_ast_export_fn_target(" in source_line and "def emit_ast_export_fn_target" not in source_line:
            if ".line" not in source_line or ".offset" not in source_line:
                raise SystemExit(f"AST export target consumer lacks declaration position: {path}: {source_line.strip()}")
        if 'annotation.name == "__export_target_ref"' in source_line and ".line ==" in source_line and ".offset ==" not in source_line:
            raise SystemExit(f"target-reference join still uses line-only identity: {path}: {source_line.strip()}")

if FIXTURE.count("#line 0 export-target-owner.elisa") != 2 or not all(
    fragment in FIXTURE
    for fragment in (
        "export fn public_first() -> i64 = target_first",
        "export fn public_second() -> i64 = target_second",
        "return public_first() + public_second() - 33",
    )
):
    raise SystemExit("fixture must exercise two distinct targets on logical line zero")
if "test_export_target_rows_use_exact_line_zero_owner" not in AST_TESTS or \
        "annotation.offset == first_offset" not in AST_TESTS or \
        "annotation.offset == second_offset" not in AST_TESTS:
    raise SystemExit("parser AST regression must pair each line-zero target row with its declaration offset")
if "check_export_target_owner_identity.py" not in SMOKE or \
        "export_target_owner_line_zero.elisa" not in SMOKE or \
        '"$STAGE0" -emit exe -O0' not in SMOKE or \
        '"$STAGE1" -emit exe' not in SMOKE:
    raise SystemExit("parity smoke must run the AST proof and execute the line-zero export fixture")

print("export target owner-offset source checks passed")
