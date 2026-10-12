"""Admit the source-linked pattern proof for @noalloc decorator arguments."""
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
POLICY = ROOT / "src/semantic/noalloc_argument_policy.elisa"
CHECK = ROOT / "src/semantic/check_noalloc_arguments.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "noalloc_argument_policy.elisa"
NEGATIVE = HERE / "noalloc_argument_policy_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def has_exact_match_table(text: str, expected_count: int, qualified_constant: bool = False) -> bool:
    constant = (
        "NoallocArgumentPolicy::NOALLOC_ARGUMENT_MINIMUM_ARGUMENTS"
        if qualified_constant else "NOALLOC_ARGUMENT_MINIMUM_ARGUMENTS"
    )
    expected = compact(f"when name: \"noalloc\" -> argument_count >= {constant} _ -> false")
    return compact(text).count(expected) == expected_count


def validate_policy(text: str) -> None:
    compact_text = compact(text)
    if "constNOALLOC_ARGUMENT_MINIMUM_ARGUMENTS:usize=1" not in compact_text:
        raise SystemExit("policy must name its minimum argument count")
    if "ensureresult==(name==\"noalloc\")" not in compact_text:
        raise SystemExit("production name classifier contract must state the exact noalloc spelling")
    if "ensureresult==(is_noalloc(name)andargument_count>=NOALLOC_ARGUMENT_MINIMUM_ARGUMENTS)" not in compact_text:
        raise SystemExit("production contract must state the exact noalloc argument rule")
    name_match = compact('when name: "noalloc" -> true _ -> false')
    if compact_text.count(name_match) != 1:
        raise SystemExit("production implementation must use the exact closed pattern table")
    if "returnis_noalloc(name)andargument_count>=NOALLOC_ARGUMENT_MINIMUM_ARGUMENTS" not in compact_text:
        raise SystemExit("production rejection result must use the proved classifier and threshold")


policy_text = POLICY.read_text()
validate_policy(policy_text)

check_text = CHECK.read_text()
if 'include "./noalloc_argument_policy.elisa"' not in check_text:
    raise SystemExit("semantic check no longer imports the proved argument policy")
if check_text.count("NoallocArgumentPolicy::rejects_decorator(decorator.name, decorator.arg_count)") != 1:
    raise SystemExit("semantic check no longer routes the diagnostic condition through the policy")
if 'decorator.name == "noalloc"' in check_text:
    raise SystemExit("semantic diagnostic still carries a separate inline name comparison")
if 'include "./check_noalloc_arguments.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("noalloc argument check is no longer included in the semantic pipeline")

proof_text = POSITIVE.read_text()
if not has_exact_match_table(proof_text, 1, qualified_constant=True):
    raise SystemExit("positive proof must state the same closed pattern table")
if 'include "../../src/semantic/noalloc_argument_policy.elisa"' not in proof_text:
    raise SystemExit("positive proof no longer imports the production policy")
if 'include "./noalloc_argument_policy.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer challenge the positive source-linked proof")

expected_positive = {
    "source_rule_matches_the_closed_pattern",
    "an_argument_on_noalloc_is_rejected",
    "bare_noalloc_is_allowed",
    "other_decorators_are_not_rejected_for_arguments",
}
expected_negative = {
    "noalloc_with_an_argument_is_allowed",
    "bare_noalloc_is_rejected",
    "another_decorator_is_rejected_for_arguments",
}
for name in expected_positive:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", proof_text):
        raise SystemExit(f"positive proof is missing {name}")
for name in expected_negative:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", NEGATIVE.read_text()):
        raise SystemExit(f"rejected proof is missing {name}")

# Ensure mutations to the closed name, threshold, fallback, or production call
# are all caught before invoking the proof executable.
mutations = (
    policy_text.replace('"noalloc" -> true', '"noallocx" -> true', 1),
    policy_text.replace('is_noalloc(name) and argument_count >= NOALLOC_ARGUMENT_MINIMUM_ARGUMENTS',
                        'not is_noalloc(name) and argument_count >= NOALLOC_ARGUMENT_MINIMUM_ARGUMENTS', 1),
    policy_text.replace('_ -> false', '_ -> argument_count > NOALLOC_ARGUMENT_MINIMUM_ARGUMENTS', 1),
)
for mutated in mutations:
    try:
        validate_policy(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("source mutation escaped the closed-table checker")
mutated_callsite = check_text.replace(
    "NoallocArgumentPolicy::rejects_decorator(decorator.name, decorator.arg_count)",
    "decorator.name == \"noalloc\" and decorator.arg_count > 0",
    1,
)
if ("NoallocArgumentPolicy::rejects_decorator(decorator.name, decorator.arg_count)" in mutated_callsite or
        'decorator.name == "noalloc" and decorator.arg_count > 0' not in mutated_callsite):
    raise SystemExit("production call-site mutation fixture is invalid")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("noalloc argument proof requires a strict proof build")

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
assert positive["summary"]["obligations"] == len(expected_positive)
assert positive["summary"]["proven"] == len(expected_positive)
assert not positive["findings"]
assert expected_positive <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == run(POSITIVE)[1], "policy proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not expected_negative & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "closed @noalloc argument rejection policy used by semantic diagnostics",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(expected_negative),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
