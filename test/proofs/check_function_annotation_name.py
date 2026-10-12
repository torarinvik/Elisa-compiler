"""Admit source-linked proofs of the Stage0 function annotation allowlists."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
STAGE0 = ROOT.parent / "compiler"
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
HELPER = ROOT / "src/semantic/function_annotation_name.elisa"
CHECK = ROOT / "src/semantic/check_unknown_function_annotation.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
STAGE0_FUNCTIONS = STAGE0 / "src/semantic/analyzer_decl_analysis.go"
STAGE0_EXTERNS = STAGE0 / "src/semantic/analyzer_annotations.go"
POSITIVE = HERE / "function_annotation_name.elisa"
NEGATIVE = HERE / "function_annotation_name_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")

if not __debug__:
    raise SystemExit("run without Python -O")


def go_allowlist(path: Path, function_name: str) -> list[str]:
    text = path.read_text()
    match = re.search(
        rf"func {re.escape(function_name)}\(name string\) bool \{{(.*?)^\}}",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise SystemExit(f"Stage0 allowlist {function_name} is missing")
    body = match.group(1)
    names = re.findall(r'case\s+([^:\n]+):', body)
    found = []
    for clause in names:
        found.extend(re.findall(r'"([^"\\]+)"', clause))
    if not found or "return false" not in body or "return true" not in body:
        raise SystemExit(f"Stage0 allowlist {function_name} has an unexpected shape")
    return found


def elisa_match_arms(text: str, function_name: str) -> list[list[str]]:
    match = re.search(
        rf"(?m)^\s*def {re.escape(function_name)}\(name: sview\) -> bool(?: can\[[^\]\n]+\])?:\n(.*?)(?=^\s*def |\Z)",
        text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit(f"production classifier {function_name} is missing")
    body = match.group(1)
    lines = body.splitlines()
    groups = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if re.match(r"^\s*(?:return\s+)?when name:\s*$", current):
            indent = len(current) - len(current.lstrip())
            index += 1
            arms = []
            while index < len(lines):
                line = lines[index]
                if line.strip() and len(line) - len(line.lstrip()) <= indent:
                    break
                if line.strip():
                    arms.append(line.strip())
                index += 1
            groups.append(arms)
            continue
        index += 1

    return [parse_literal_arms(arms, function_name) for arms in groups]


def parse_literal_arms(arms: list[str], description: str) -> list[str]:
    if not arms or arms[-1] != "_ -> false":
        raise SystemExit(f"{description} lost its false pattern fallback")
    found = []
    for arm in arms[:-1]:
        if not re.fullmatch(r'"[^"\\]+"(?:\s*\|\s*"[^"\\]+")*\s*->\s*true', arm):
            raise SystemExit(f"{description} contains a nonliteral or non-true match arm")
        found.extend(re.findall(r'"([^"\\]+)"', arm))
    return found


function_names = go_allowlist(STAGE0_FUNCTIONS, "isSupportedFunctionAnnotation")
extern_names = go_allowlist(STAGE0_EXTERNS, "isSupportedExternFunctionAnnotation")
helper_text = HELPER.read_text()
proof_text = POSITIVE.read_text()
check_text = CHECK.read_text()
if elisa_match_arms(helper_text, "is_function_annotation") != [function_names, function_names]:
    raise SystemExit("ordinary Stage1 match arms differ from the ordered Stage0 allowlist")
if elisa_match_arms(helper_text, "is_extern_function_annotation") != [extern_names, extern_names]:
    raise SystemExit("extern Stage1 match arms differ from the ordered Stage0 allowlist")
if elisa_match_arms(proof_text, "source_function_annotation_match_is_exact") != [function_names]:
    raise SystemExit("ordinary proof contract differs from the Stage0 allowlist")
if elisa_match_arms(proof_text, "source_extern_function_annotation_match_is_exact") != [extern_names]:
    raise SystemExit("extern proof contract differs from the Stage0 allowlist")
if 'include "./function_annotation_name.elisa"' not in check_text:
    raise SystemExit("production annotation checker no longer imports the proved classifiers")
if "FunctionAnnotationName::is_function_annotation(name)" not in check_text:
    raise SystemExit("ordinary annotation checker no longer uses the proved classifier")
if "FunctionAnnotationName::is_extern_function_annotation(name)" not in check_text:
    raise SystemExit("extern annotation checker no longer uses the proved classifier")
if 'include "./check_unknown_function_annotation.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("function annotation checker is no longer in the semantic pipeline")
if f'include "../../src/semantic/function_annotation_name.elisa"' not in proof_text:
    raise SystemExit("positive proof no longer imports the production classifiers")
if 'include "./function_annotation_name.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer import the positive source-linked proof")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("function annotation proofs require a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CHECK])
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", STAGE0_FUNCTIONS, STAGE0_EXTERNS,
    *source_closure,
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
assert positive == run(POSITIVE)[1], "function annotation proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "is_function_annotation",
    "is_extern_function_annotation",
    "source_function_annotation_match_is_exact",
    "source_extern_function_annotation_match_is_exact",
    "every_stage0_function_annotation_is_accepted",
    "every_stage0_extern_function_annotation_is_accepted",
    "unrelated_annotation_names_stay_rejected",
}
assert expected <= verified

code, negative = run(NEGATIVE)
negative_names = {
    "stage1_only_c_variadic_must_not_be_accepted",
    "extern_only_annotation_must_not_be_ordinary",
    "ordinary_only_annotation_must_not_be_extern",
}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == product_manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "ordinary and extern function annotation name allowlists",
    "ordinary_annotations": function_names,
    "extern_annotations": extern_names,
    "false_claims_rejected": sorted(negative_names),
    "positive_obligations": positive["summary"]["proven"],
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
