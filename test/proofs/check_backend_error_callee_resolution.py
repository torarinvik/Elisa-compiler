"""Admit the proof of fallible-callee owner precedence and fallback shielding."""
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
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof"))
SOURCE = ROOT / "src/backend/codegen_error_callee_facts.elisa"
POSITIVE = HERE / "backend_error_callee_resolution.elisa"
NEGATIVE = HERE / "backend_error_callee_resolution_rejected.elisa"

POSITIVE_SHAPES = {
    "unique_error_fallback_gate_is_exact": (
        "ensure result == (not explicit_declared and not current_declared and not top_declared and unique_error) "
        "return not explicit_declared and not current_declared and not top_declared and unique_error"
    ),
    "explicit_owner_blocks_fallback": (
        "requires explicit_declared and unique_error ensure result == false "
        "return not explicit_declared and not current_declared and not top_declared and unique_error"
    ),
    "ordinary_lexical_declaration_shields_unrelated_error": (
        "requires not explicit_declared and current_declared and not current_is_error and unique_error "
        "ensure result == true return not (not explicit_declared and not current_declared and not top_declared and unique_error)"
    ),
    "top_level_declaration_shields_unique_error": (
        "requires not explicit_declared and not current_declared and top_declared and unique_error "
        "ensure result == true return not (not explicit_declared and not current_declared and not top_declared and unique_error)"
    ),
    "unique_error_is_used_only_after_all_declaration_misses": (
        "requires not explicit_declared and not current_declared and not top_declared and unique_error "
        "ensure result == true return not explicit_declared and not current_declared and not top_declared and unique_error"
    ),
    "exactly_one_fallible_owner_enables_fallback": (
        "ensure result == (owner_hits == 1) return owner_hits == 1"
    ),
}
NEGATIVE_NAMES = {
    "false_claim_explicit_owner_allows_fallback",
    "false_claim_ordinary_lexical_allows_fallback",
    "false_claim_top_level_declared_allows_fallback",
    "false_claim_multiple_error_owners_are_unique",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


source_text = SOURCE.read_text()
owner_body = compact(function_section(source_text, "error_callee_owner"))
ordered_source_shapes = (
    'returnowner_hintifowner_hint!=""andfunction_is_declared(fns,owner_hint,name)',
    'returnstructs.visibility.current_ownerifstructs.visibility.current_owner!=""andfunction_is_declared(fns,structs.visibility.current_owner,name)',
    'return""iffunction_is_declared(fns,"",name)',
    'unique_owner:mutablesview=""',
    'owner_hits:mutablei64=0',
    'owner_index_cursor:mutablei64=first_function_named(fns,name)',
    'iffns.names[owner_index]==nameandfns.is_error[owner_index]',
    'owner_hits<-owner_hits+1',
    'returnunique_ownerifowner_hits==1else""',
)
positions = [owner_body.find(fragment) for fragment in ordered_source_shapes]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("fallible-callee owner precedence or unique-error fallback changed")
declared_body = compact(function_section(source_text, "function_is_declared"))
if "returnfunction_index_of(fns,owner,name)>=0" not in declared_body:
    raise SystemExit("lexical shadowing must recognize every declaration, including ordinary functions")

positive_names = set(POSITIVE_SHAPES)
if declarations(POSITIVE) != positive_names or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("fallible-callee proof inventory is incomplete or contains extras")
for name, shape in POSITIVE_SHAPES.items():
    if compact(shape) not in compact(function_section(POSITIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer states its intended owner-precedence property")
if 'include "./backend_error_callee_resolution.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the positive owner-resolution proof")

if args.source_only:
    print(json.dumps({"source_bound": True, "owner_precedence_shapes": len(ordered_source_shapes)}))
    raise SystemExit(0)

BIN = BIN.resolve(strict=True)
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("fallible-callee owner proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 12
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(NEGATIVE_NAMES)
assert negative["summary"]["obligations"] == 20 and negative["summary"]["proven"] == 16
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay or final provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "explicit and lexical declarations suppress unique error-function fallback; a unique error owner is used only after declaration lookup misses",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
