"""Bind C-string/StringView equality boundary proofs to collection lookup code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
COLLECTIONS = ROOT / "elisacore_std/collections.elisa"
POSITIVE = HERE / "cstr_sview_equality_bounds.elisa"
NEGATIVE = HERE / "cstr_sview_equality_bounds_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()
if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


collections_text = COLLECTIONS.read_text()
compare = compact(function_section(collections_text, "ctx_cstr_eq_sview"))
contracts = (
    "ensure (view.len < 0 or view.len.usize().i64() != view.len) implies result == false",
    "ensure text.len != view.len implies result == false",
    "ensure result implies (view.len >= 0 and view.len.usize().i64() == view.len and text.len == view.len)",
    "ensure (view.len == 0 and text.len == 0) implies result == true",
)
if any(compact(contract) not in compare for contract in contracts):
    raise SystemExit("ctx_cstr_eq_sview lost its invalid-extent, length, or empty-input contract")
steps = (
    "false return if view.len < 0",
    "len: usize = view.len.usize()",
    "false return if len.i64() != view.len",
    "false return if text.len != view.len",
    "i: mutable usize = 0",
    "while i < len:",
    "decreases len - i",
    "invariant i <= len",
    "invariant i.i64().usize() == i",
    "invariant len.i64() == view.len",
    "invariant text.len == view.len",
    "view_byte: u8 = view[i].u8()",
    "text_byte: mutable u8 = 0",
    "trusted Unsafe.UncheckedIndex: text_byte <- text[i].u8()",
    "false return if text_byte != view_byte",
    "i <- i + 1.usize()",
    "return true",
)
positions = [compare.find(compact(step)) for step in steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("ctx_cstr_eq_sview lost its extent guards, bounded loop, or byte comparison")
if "view.data[" in compare or "text[len]" in compare or "trustedUnsafe.UncheckedIndex:while" in compare:
    raise SystemExit("ctx_cstr_eq_sview regressed to raw view reads, a one-past-end terminator read, or a trusted loop")

positive_claims = {
    "malformed_view_never_matches_a_cstr": "not ctx_cstr_eq_sview(text, view)",
    "unequal_lengths_never_match": "not ctx_cstr_eq_sview(text, view)",
    "a_reported_match_has_a_valid_equal_extent": "not ctx_cstr_eq_sview(text, view) or (view.len >= 0 and view.len.usize().i64() == view.len and text.len == view.len)",
    "equal_empty_cstr_and_view_match": "ctx_cstr_eq_sview(text, view)",
}
positive_requires = {
    "malformed_view_never_matches_a_cstr": "requires view.len < 0 or view.len.usize().i64() != view.len",
    "unequal_lengths_never_match": "requires text.len != view.len",
    "equal_empty_cstr_and_view_match": "requires text.len == 0 and view.len == 0",
}
negative_claims = {
    "a_malformed_view_can_match_a_cstr": "ctx_cstr_eq_sview(text, view)",
    "unequal_lengths_can_match": "ctx_cstr_eq_sview(text, view)",
}
negative_requires = {
    "a_malformed_view_can_match_a_cstr": "requires view.len < 0 or view.len.usize().i64() != view.len",
    "unequal_lengths_can_match": "requires text.len != view.len",
}
for path, claims, requirements, label in (
    (POSITIVE, positive_claims, positive_requires, "positive"),
    (NEGATIVE, negative_claims, negative_requires, "negative"),
):
    fixture = path.read_text()
    if declarations(fixture) != set(claims):
        raise SystemExit(f"{label} C-string/StringView equality theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in fixture \
            or 'include "../../elisacore_std/collections.elisa"' not in fixture:
        raise SystemExit(f"{label} C-string/StringView proofs no longer import production equality")
    for name, claim in claims.items():
        section = compact(function_section(fixture, name))
        if compact("ensure result == true") not in section \
                or compact(claim) not in section \
                or (name in requirements and compact(requirements[name]) not in section) \
                or compact("ctx_cstr_eq_sview(text, view)") not in section:
            raise SystemExit(f"{label} C-string/StringView theorem {name} lost its claim or source binding")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if COLLECTIONS not in source_closure:
    raise SystemExit("proof include closure no longer contains ctx_cstr_eq_sview production source")
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_claims),
                      "false_claim_controls": len(negative_claims),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("C-string/StringView equality proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", COLLECTIONS, POSITIVE, NEGATIVE, *source_closure,
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
assert positive["summary"]["declarations"] == len(positive_claims)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == set(positive_claims)

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == set(negative_claims)
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not set(negative_claims) & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "C-string/StringView equality rejects malformed and unequal extents, compares within a bounded view, and succeeds for equal empty strings",
    "positive_claims_proved": sorted(positive_claims),
    "false_claims_refused": sorted(negative_claims),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
