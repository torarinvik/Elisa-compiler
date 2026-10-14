"""Bind error-union variant admission proofs to the backend annotation scan."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
SOURCE = ROOT / "src/backend/codegen_error_union_reg.elisa"
PROOF = HERE / "backend_error_variant_allow.elisa"
ANNOTATION_PROOF = HERE / "backend_error_variant_annotation_match.elisa"


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^([ \t]*)def {re.escape(name)}\(", text)
    if match is None:
        raise SystemExit(f"missing function {name}")
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_]\w*\(", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


source = compact(section(SOURCE.read_text(), "error_union_variant_allowed"))
production_fragments = (
    'forannotationinfile.enum_annotations|restricted,line,family|:',
    'restricted<-trueifannotation.owner=="__error_variant_family"andannotation.line==lineandannotation.name==family',
    'returntrueifnotrestricted',
    'continueifannotation.owner!="__error_variant_family"orannotation.line!=lineorannotation.name!=family',
    'continueifannotation_index+1>=file.enum_annotations.count',
    'allowed:Ast::EnumAnnotation=file.enum_annotations[annotation_index+1]',
    'returntrueifallowed.owner=="__error_variant_allow"andallowed.line==lineandallowed.name==variant',
    'returnfalse',
)
if not all(fragment in source for fragment in production_fragments):
    raise SystemExit("error-union variant admission no longer matches the proved unrestricted/restricted policy")
if 'allowed.owner=="__error_variant_allow"andallowed.line==lineandallowed.name==variant' not in source:
    raise SystemExit("restricted variant admission no longer requires matching owner, line, and variant")

proof = PROOF.read_text()
expected = {
    "restricted_error_variant_is_allowed": """
        def restricted_error_variant_is_allowed(is_restricted: bool, has_immediate_allow: bool) -> bool:
            ensure result == (not is_restricted or has_immediate_allow)
            return not is_restricted or has_immediate_allow
    """,
    "unrestricted_error_family_allows_variants": """
        def unrestricted_error_family_allows_variants() -> bool:
            ensure result == true
            return restricted_error_variant_is_allowed(false, false)
    """,
    "restricted_error_family_accepts_explicit_variant": """
        def restricted_error_family_accepts_explicit_variant() -> bool:
            ensure result == true
            return restricted_error_variant_is_allowed(true, true)
    """,
    "restricted_error_family_rejects_unlisted_variant": """
        def restricted_error_family_rejects_unlisted_variant() -> bool:
            ensure result == false
            return restricted_error_variant_is_allowed(true, false)
    """,
}
for name, shape in expected.items():
    if compact(section(proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
annotation_expected = {
    "error_variant_allow_annotation_matches": """
        def error_variant_allow_annotation_matches(is_allow_owner: bool, same_line: bool, same_variant: bool) -> bool:
            ensure result == (is_allow_owner and same_line and same_variant)
            return is_allow_owner and same_line and same_variant
    """,
    "wrong_owner_allow_marker_is_rejected": """
        def wrong_owner_allow_marker_is_rejected(same_line: bool, same_variant: bool) -> bool:
            ensure result == false
            return error_variant_allow_annotation_matches(false, same_line, same_variant)
    """,
    "wrong_line_allow_marker_is_rejected": """
        def wrong_line_allow_marker_is_rejected(is_allow_owner: bool, same_variant: bool) -> bool:
            ensure result == false
            return error_variant_allow_annotation_matches(is_allow_owner, false, same_variant)
    """,
    "wrong_variant_allow_marker_is_rejected": """
        def wrong_variant_allow_marker_is_rejected(is_allow_owner: bool, same_line: bool) -> bool:
            ensure result == false
            return error_variant_allow_annotation_matches(is_allow_owner, same_line, false)
    """,
    "matching_allow_marker_is_accepted": """
        def matching_allow_marker_is_accepted() -> bool:
            ensure result == true
            return error_variant_allow_annotation_matches(true, true, true)
    """,
}
annotation_proof = ANNOTATION_PROOF.read_text()
for name, shape in annotation_expected.items():
    if compact(section(annotation_proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")

if args.source_only:
    print(json.dumps({"source_bound": True, "theorems": len(expected) + len(annotation_expected)}, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("error-union variant proofs require a strict Elisa-Proof build")
closure = source_include_closure([PROOF, ANNOTATION_PROOF])
inputs = [Path(__file__), HERE / "proof_product_gate.py", SOURCE, PROOF, ANNOTATION_PROOF, *closure,
          BIN, BIN.with_name(BIN.name + ".manifest.json"), PROVER / "ELISA_COMPILER_REV"]
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in dict.fromkeys(inputs)}
reports = []
for proof_path in (PROOF, ANNOTATION_PROOF):
    run = subprocess.run([str(BIN), "--json", str(proof_path)], capture_output=True, text=True, timeout=60)
    report = json.loads(run.stdout)
    summary = report.get("summary", {})
    replay = report.get("replay", {})
    if (run.returncode != 0 or report.get("status") != "proved" or
            summary.get("semantic_errors") != 0 or summary.get("unproven") != 0 or
            summary.get("proven") != summary.get("obligations") or
            replay.get("certificates") != replay.get("replayed") or replay.get("gaps") != 0 or
            report.get("trust", {}).get("trusted_assumptions")):
        raise SystemExit(f"error-union variant proof replay failed for {proof_path.name}: {summary}")
    reports.append(report)
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in dict.fromkeys(inputs)} != before:
    raise SystemExit("error-union proof inputs changed during replay")
print(json.dumps({"source_bound": True, "proved": sum(report["summary"]["proven"] for report in reports), "replay_gaps": sum(report["replay"]["gaps"] for report in reports)}, sort_keys=True))
