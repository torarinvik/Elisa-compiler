"""Admit source-linked proof of nested-container element type classification."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "region_escape_container_element_type.elisa"
NEGATIVE = HERE / "region_escape_container_element_type_rejected.elisa"
STORES = ROOT / "src/semantic/region_escape_stores.elisa"
AUTO_REGION = ROOT / "src/semantic/check_auto_region_escape.elisa"
REGION_CHECK = ROOT / "src/semantic/check_region_escape.elisa"
SEMANTIC_ROOT = ROOT / "src/semantic/semantic.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")


def compact_function(path: Path, name: str) -> str:
    source = path.read_text()
    start = source.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"production region type helper is missing: {name}")
    end = source.find("\n        def ", start + len(f"def {name}("))
    code = re.sub(r"#.*$", "", source[start:end if end >= 0 else None], flags=re.MULTILINE)
    return "".join(code.split())


receiver = compact_function(STORES, "receiver_elements_are_containers")
receiver_arms = (
    "ifannotation_lookupisannotation:returncontainer_element_is_container(annotation.type_expression)",
    "local_type:(found:bool,type_expression:Ast::Expr)=region_escape_local_type_find(receiver,local_names,local_types)",
    "returncontainer_element_is_container(local_type.type_expression)iflocal_type.found",
    "returnfalse",
)
for arm in receiver_arms:
    if arm not in receiver:
        raise SystemExit(f"receiver element-type precedence changed without updating its proof: {arm}")

element = compact_function(STORES, "container_element_is_container")
element_arms = (
    "Expr.Unary(operator,operand,line):returncontainer_element_is_container(operand)",
    "Expr.Paren(inner,paren_line):returncontainer_element_is_container(inner)",
    "Expr.Index(object,element,index_line):head:sview=ident_name_of(object)",
    'returnwhenhead:"darray"|"dict"->annotation_is_container(element)_ ->false',
    "Expr.IndexN(object_n,arguments_n,line_n):head_n:sview=ident_name_of(object_n)",
    'returnwhenhead_n:"darray"|"dict"->anyargumentinarguments_nwhereannotation_is_container(argument)_ ->false',
    "_:returnfalse",
)
for arm in element_arms:
    if "".join(arm.split()) not in element:
        raise SystemExit(f"nested-container element classifier changed without updating its proof: {arm}")

annotation = compact_function(AUTO_REGION, "annotation_is_container")
annotation_arms = (
    'Expr.Index(object,index,line):head:sview=ident_name_of(object)returnwhenhead:"darray"|"dict"->true_->false',
    'Expr.IndexN(object_n,arguments_n,line_n):head_n:sview=ident_name_of(object_n)returnwhenhead_n:"darray"|"dict"->true_->false',
    "Expr.Unary(operator,operand,line):returnannotation_is_container(operand)",
    "Expr.Paren(inner,paren_line):returnannotation_is_container(inner)",
    "_:returnfalse",
)
for arm in annotation_arms:
    if arm not in annotation:
        raise SystemExit(f"container annotation grammar changed without updating its proof: {arm}")

semantic = SEMANTIC_ROOT.read_text()
if 'include "./check_auto_region_escape.elisa"' not in semantic:
    raise SystemExit("semantic entry no longer includes the proved container annotation predicate")
if 'include "./check_region_escape.elisa"' not in semantic:
    raise SystemExit("semantic entry no longer includes the region growth checker")
if 'include "./region_escape_stores.elisa"' not in REGION_CHECK.read_text():
    raise SystemExit("region growth checker no longer includes the proved element classifier")
if "receiver_elements_are_containers(" not in STORES.read_text():
    raise SystemExit("region store path no longer calls the proved receiver element classifier")

expected = {
    "receiver_element_classification_is_exact",
    "explicit_annotation_takes_precedence_over_inferred_type",
    "inferred_local_type_is_used_when_annotation_is_absent",
    "missing_annotation_and_local_type_is_conservatively_false",
    "container_type_head_classification_is_exact",
    "one_argument_container_element_classification_is_exact",
    "multiple_argument_container_element_classification_is_exact",
    "unary_and_parenthesized_type_wrappers_preserve_container_classification",
    "unsupported_type_shape_is_conservatively_false",
}
declarations = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
if not expected <= declarations:
    raise SystemExit("nested-container type proof lost a branch or precedence law")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("nested-container type proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE, STORES, AUTO_REGION, REGION_CHECK, SEMANTIC_ROOT])]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "explicit_scalar_annotation_falls_back_to_nested_inferred_type"),
    ("ensure-unproven", "unsupported_container_head_is_treated_as_darray_or_dict"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "container element classification for region-sensitive extend behavior",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "sources_sha256": hashes_before,
}, sort_keys=True))
