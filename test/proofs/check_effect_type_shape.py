"""Admit proofs of the AST helpers used to identify and lower static effects."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
MODEL = HERE / "effect_type_shape_proof_model.elisa"
POSITIVE = HERE / "effect_type_shape.elisa"
NEGATIVE = HERE / "effect_type_shape_rejected.elisa"
HELPER = ROOT / "src/parser/effect_type_shape.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
PARSER_TYPES = ROOT / "src/parser/parser_tokens.elisa"
PARSER = ROOT / "src/parser/parser.elisa"
DEFERRED = ROOT / "src/parser/parser_effect_deferred.elisa"
BACKEND = ROOT / "src/backend/codegen.elisa"
BACKEND_STATIC_EFFECTS = ROOT / "src/backend/codegen_static_effects.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def function_region(source: str, name: str) -> str:
    match = re.search(rf"^([ \t]*)def {re.escape(name)}\(", source, re.M)
    if not match:
        raise SystemExit(f"missing function {name}")
    end = re.search(rf"^{re.escape(match.group(1))}def ", source[match.end():], re.M)
    return source[match.start():match.end() + end.start()] if end else source[match.start():]


def include_closure(roots: list[Path]) -> list[Path]:
    include = re.compile(r'^\s*include\s+"([^"]+)"', re.MULTILINE)
    pending = list(roots)
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in seen:
            continue
        seen.add(path)
        for relative in include.findall(path.read_text()):
            child = (path.parent / relative).resolve(strict=True)
            if child not in seen:
                pending.append(child)
    return sorted(seen)


model_text = compact(MODEL.read_text())
positive_text = compact(POSITIVE.read_text())
negative_text = compact(NEGATIVE.read_text())
helper_text = compact(HELPER.read_text())
ast_nodes_text = compact(AST_NODES.read_text())
ast_tables_text = compact(AST_TABLES.read_text())
parser_types_text = compact(PARSER_TYPES.read_text())
parser_text = compact(PARSER.read_text())
deferred_text = compact(DEFERRED.read_text())
backend_text = compact(BACKEND.read_text())
backend_effects_text = compact(BACKEND_STATIC_EFFECTS.read_text())

if 'include"../../src/parser/effect_type_shape.elisa"' not in model_text:
    raise SystemExit("proof model no longer imports the production effect-shape helper")
if 'include"./effect_type_shape_proof_model.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the checked AST projection")
if 'include"./effect_type_shape.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer import the positive effect-shape proof")

projected_ast_fragments = (
    "enumNodelayout(handle:u32):pass",
    "enumExprisNode:",
    "Absent",
    "Ident(name:sview,pos:Pos)",
    "Scope(base:Expr,name:sview,pos:Pos)",
    "Index(object:Expr,index:Expr,pos:Pos)",
    "IndexN(object:Expr,arguments:darray[Expr],pos:Pos)",
    "structPos:line:mutableu32column:mutableu32offset:mutableu32end_line:mutableu32end_column:mutableu32end_offset:mutableu32",
    "structStaticEffectCandidate:",
    "captures:darray[Expr]",
)
for fragment in projected_ast_fragments:
    if fragment not in model_text:
        raise SystemExit(f"proof AST projection is missing {fragment}")
for fragment in projected_ast_fragments[:7]:
    if fragment not in ast_nodes_text:
        raise SystemExit(f"modeled Expr constructor no longer matches production AST: {fragment}")
for field in ("line", "column", "offset", "end_line", "end_column", "end_offset"):
    if f"{field}:mutableu32" not in parser_types_text:
        raise SystemExit(f"modeled position field {field} no longer matches the production AST")
if "structStaticEffectCandidate:" not in ast_tables_text or "captures:darray[Expr]" not in ast_tables_text:
    raise SystemExit("StaticEffectCandidate capture projection no longer matches the production AST")

head = compact(function_region(HELPER.read_text(), "effect_application_head"))
arguments = compact(function_region(HELPER.read_text(), "effect_application_arguments"))
path_equal = compact(function_region(HELPER.read_text(), "effect_path_equal"))
runtime_children = compact(function_region(HELPER.read_text(), "effect_runtime_children"))
for body, fragments, name in (
    (head, ("Expr.Index(head,argument,position):returnhead",
            "Expr.IndexN(head,arguments,position):returnhead",
            "_:returnexpression"), "effect_application_head"),
    (arguments, ("Expr.Index(head,argument,position):return[argument]",
                 "Expr.IndexN(head,arguments,position):returnarguments",
                 "_:return[]"), "effect_application_arguments"),
    (path_equal, ("Expr.Ident(left_name,left_position):ifrightisExpr.Ident(right_name,right_position):returnleft_name==right_name",
                  "Expr.Scope(left_head,left_name,left_position):ifrightisExpr.Scope(right_head,right_name,right_position):returnleft_name==right_nameandeffect_path_equal(left_head,right_head)",
                  "returnfalse"), "effect_path_equal"),
    (runtime_children, ("forcandidateincandidates|children|:children.extend(candidate.captures)",
                        "children.extend(arguments)", "returnchildren"), "effect_runtime_children"),
):
    if any(fragment not in body for fragment in fragments):
        raise SystemExit(f"production {name} behavior no longer matches the source-linked proof contract")

if 'include"./effect_type_shape.elisa"' not in parser_text:
    raise SystemExit("production parser no longer imports the proved effect-shape helper")
if 'include"./codegen_static_effects.elisa"' not in backend_text:
    raise SystemExit("production backend no longer imports static-effect lowering")
if "Ast::effect_path_equal(Ast::effect_application_head(requested),Ast::effect_application_head(candidate))" not in deferred_text:
    raise SystemExit("deferred effect resolution no longer selects candidates through the proved path helpers")
if "Ast::effect_path_equal(Ast::effect_application_head(requested),Ast::effect_application_head(installed))" not in backend_effects_text:
    raise SystemExit("backend lowering no longer selects installations through the proved path helpers")
if "Ast::effect_application_arguments(requested)" not in backend_effects_text or "Ast::effect_application_arguments(installed)" not in backend_effects_text:
    raise SystemExit("backend type application matching no longer uses the proved argument projection")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("static-effect identity proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *include_closure([POSITIVE, NEGATIVE, MODEL]), AST_NODES, AST_TABLES, PARSER_TYPES,
    PARSER, DEFERRED, BACKEND, BACKEND_STATIC_EFFECTS,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "effect-shape proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "effect_runtime_children",
    "effect_application_head",
    "effect_application_arguments",
    "effect_path_equal",
    "effect_path_form",
    "self_comparison_matches_the_recursive_effect_path_form",
    "effect_path_equality_is_symmetric",
    "identifier_path_equality_ignores_positions_and_compares_names_exactly",
    "one_level_effect_paths_compare_each_segment",
    "two_level_effect_paths_compare_all_segments",
    "index_application_decomposes_to_its_head_and_single_argument",
    "multi_index_application_preserves_argument_order",
    "unapplied_identifier_has_itself_as_head_and_no_arguments",
    "one_candidate_runtime_children_keep_captures_before_call_arguments",
} <= verified

code, negative = run(NEGATIVE)
false_claims = {
    "same_effect_path_with_different_positions_is_not_equal",
    "different_effect_roots_with_same_member_are_equal",
    "captures_are_not_part_of_static_effect_runtime_children",
}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(false_claims) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == false_claims
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not false_claims & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == product_manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "static-effect path identity, application argument projection, and capture ordering",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(false_claims),
    "sources_sha256": hashes_before,
}, sort_keys=True))
