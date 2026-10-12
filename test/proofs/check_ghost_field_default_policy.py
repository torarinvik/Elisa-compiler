"""Admit source-linked proofs of ghost-field default diagnostics."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POLICY = ROOT / "src/semantic/ghost_field_default_policy.elisa"
CHECK = ROOT / "src/semantic/check_ghost_field_default.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "ghost_field_default_policy.elisa"
NEGATIVE = HERE / "ghost_field_default_policy_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def {re.escape(name)}\([^\n]*\n(.*?)(?=^\s*def |\Z)", text, re.DOTALL)
    if not match:
        raise SystemExit(f"missing source policy function {name}")
    return match.group(1)


def validate_policy(text: str) -> None:
    if "const MISSING_FIELD_SOURCE_LINE: u32 = 0" not in text:
        raise SystemExit("missing-field location sentinel must be a named constant")
    predicate = compact(function_section(text, "should_report"))
    if ("ensureresult==(is_ghostandhas_default)" not in predicate or
            "returnis_ghostandhas_default" not in predicate):
        raise SystemExit("production ghost/default predicate no longer matches its proved boolean rule")
    line_rule = compact(function_section(text, "diagnostic_line"))
    expected_line_rule = compact(
        "ensure result == (struct_line if field_type_line == MISSING_FIELD_SOURCE_LINE else field_type_line) "
        "return struct_line if field_type_line == MISSING_FIELD_SOURCE_LINE else field_type_line"
    )
    if expected_line_rule not in line_rule:
        raise SystemExit("production diagnostic location no longer uses the named missing-line fallback")


policy_text = POLICY.read_text()
validate_policy(policy_text)

check_text = CHECK.read_text()
if 'include "./ghost_field_default_policy.elisa"' not in check_text:
    raise SystemExit("semantic checker no longer imports the proved ghost-field policy")
if "GhostFieldDefaultPolicy::should_report(member.is_ghost, member.has_default)" not in check_text:
    raise SystemExit("semantic checker no longer uses the proved ghost/default predicate")
if "GhostFieldDefaultPolicy::diagnostic_line(line.line, Ast::expr_pos(member.type_expression).line)" not in check_text:
    raise SystemExit("semantic checker no longer uses the proved field-location rule")
if 'include "./check_ghost_field_default.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("ghost-field diagnostic is no longer part of the semantic pipeline")

proof_text = POSITIVE.read_text()
if 'include "../../src/semantic/ghost_field_default_policy.elisa"' not in proof_text:
    raise SystemExit("positive proof no longer imports the production policy")
positive_names = {
    "source_predicate_matches_the_boolean_cases",
    "source_location_uses_the_field_or_struct_fallback",
    "ghost_field_with_default_is_reported",
    "non_ghost_field_with_default_is_not_reported",
    "ghost_field_without_default_is_not_reported",
    "field_type_location_is_preferred",
    "missing_field_type_location_uses_the_struct",
}
negative_names = {
    "non_ghost_default_is_reported",
    "ghost_without_default_is_reported",
    "struct_location_wins_when_field_location_exists",
    "missing_field_location_returns_the_sentinel",
}
for name in positive_names:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", proof_text):
        raise SystemExit(f"positive proof is missing {name}")
negative_text = NEGATIVE.read_text()
for name in negative_names:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", negative_text):
        raise SystemExit(f"rejected proof is missing {name}")
if 'include "./ghost_field_default_policy.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer challenge the source-linked policy")

# Representative source mutations must invalidate their respective bindings.
policy_mutations = (
    policy_text.replace("is_ghost and has_default", "is_ghost and not has_default", 1),
    policy_text.replace("const MISSING_FIELD_SOURCE_LINE: u32 = 0", "const MISSING_FIELD_SOURCE_LINE: u32 = 1", 1),
    policy_text.replace("struct_line if field_type_line == MISSING_FIELD_SOURCE_LINE else field_type_line",
                        "field_type_line if field_type_line == MISSING_FIELD_SOURCE_LINE else struct_line", 1),
)
for mutated in policy_mutations:
    try:
        validate_policy(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("production policy mutation escaped its source checker")

def validate_routing(text: str) -> None:
    if 'include "./ghost_field_default_policy.elisa"' not in text:
        raise SystemExit("semantic checker no longer imports the proved ghost-field policy")
    if "GhostFieldDefaultPolicy::should_report(member.is_ghost, member.has_default)" not in text:
        raise SystemExit("semantic checker no longer uses the proved ghost/default predicate")
    if "GhostFieldDefaultPolicy::diagnostic_line(line.line, Ast::expr_pos(member.type_expression).line)" not in text:
        raise SystemExit("semantic checker no longer uses the proved field-location rule")


validate_routing(check_text)
for mutated in (
    check_text.replace("GhostFieldDefaultPolicy::should_report(member.is_ghost, member.has_default)", "member.is_ghost", 1),
    check_text.replace("GhostFieldDefaultPolicy::diagnostic_line(line.line, Ast::expr_pos(member.type_expression).line)", "line.line", 1),
):
    try:
        validate_routing(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("production call-site mutation escaped its source checker")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("ghost-field policy proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CHECK, SEMANTIC])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", *source_closure,
]))
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
assert positive["summary"]["obligations"] == len(positive_names)
assert positive["summary"]["proven"] == len(positive_names)
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "ghost-field proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "ghost-field default diagnostic decision and field source location",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
