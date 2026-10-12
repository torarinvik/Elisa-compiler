"""Admit source-pinned proofs of the guarded char-classifier diagnostic shape."""
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
POSITIVE = HERE / "char_classifier_guard.elisa"
NEGATIVE = HERE / "char_classifier_guard_rejected.elisa"
CHECKER = ROOT / "src/semantic/check_char_classifier_guard.elisa"
SEMANTIC_ROOT = ROOT / "src/semantic/semantic.elisa"
PASS_CALLER = ROOT / "src/semantic/semantic_parallel_passes.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")


def compact_function(source: str, name: str) -> str:
    start = source.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"production classifier helper is missing: {name}")
    end = source.find("\n        def ", start + len(f"def {name}("))
    body = re.sub(r"#.*$", "", source[start:end if end >= 0 else None], flags=re.MULTILINE)
    return "".join(body.split())


source = CHECKER.read_text()
body_shape = compact_function(source, "classifier_body_has_guarded_arm")
for step in (
    "falsereturnifbody.count!=1",
    "Stmt.Return(value,line)",
    "Expr.Match(scrutinee,arms,match_line):",
    "falsereturnifident_name_of(scrutinee)!=param_name",
    "returnanyarminarmswherenot(arm.guardisExpr.Absent)",
    "_:returnfalse",
):
    if step not in body_shape:
        raise SystemExit(f"production guarded-body condition changed without updating its proof: {step}")

classifier_shape = compact_function(source, "char_classifier_guard_walk")
shape_gate = (
    "classifier_shaped:bool=parameters.count==1and"
    'bare_type_name(parameters[0].type_expression)=="char"and'
    "classifier_enum_name_present(const_enums,classifier_return_type_name(return_type))"
)
diagnostic_gate = (
    "ifclassifier_shapedandclassifier_body_has_guarded_arm(body,parameters[0].name)"
)
if shape_gate not in classifier_shape or diagnostic_gate not in classifier_shape:
    raise SystemExit("production classifier diagnostic no longer requires the exact proved conjunction")

enum_lookup = compact_function(source, "classifier_enum_name_present")
if "returnanynameinnameswherename==wanted" not in enum_lookup:
    raise SystemExit("closed-enum return predicate changed without updating its proof")
return_type = compact_function(source, "classifier_return_type_name")
if "ifreturn_typeispresent:returnbare_type_name(present)" not in return_type:
    raise SystemExit("classifier return type projection changed without updating its proof")

if 'include "./check_char_classifier_guard.elisa"' not in SEMANTIC_ROOT.read_text():
    raise SystemExit("semantic root no longer includes the proved char-classifier pass")
if "check_char_classifier_guard(loop_view.top_decls, table)" not in PASS_CALLER.read_text():
    raise SystemExit("semantic pass runner no longer executes the proved char-classifier check")

positive_names = {
    "exact_guarded_char_classifier_is_rejected",
    "every_source_shape_requirement_is_part_of_the_guard",
    "each_failed_shape_suppresses_the_diagnostic",
}
negative_names = {
    "extra_parameter_char_function_is_misdiagnosed",
    "guardless_classifier_is_misdiagnosed",
    "classifier_for_non_enum_return_is_misdiagnosed",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    found = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", path.read_text()))
    if not expected <= found:
        raise SystemExit(f"{path.name} lost a classifier guard law: {sorted(expected - found)}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("char-classifier guard proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE]), CHECKER, SEMANTIC_ROOT, PASS_CALLER]
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
assert positive == run(POSITIVE)[1], "char-classifier proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "exact AST-shape gate for const-enum char classifier guards",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": sorted(negative_names),
                  "sources_sha256": hashes_before}, sort_keys=True))
