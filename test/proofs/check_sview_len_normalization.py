"""Bind StringView length normalization claims to the runtime helper."""
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
RUNTIME = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
POSITIVE = HERE / "sview_len_normalization.elisa"
NEGATIVE = HERE / "sview_len_normalization_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(
        rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(",
        source[match.end():],
    )
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


runtime_text = RUNTIME.read_text()
sview_len = compact(function_section(runtime_text, "sview_len"))
normalization_contract = (
    "ensure ((view.len <= 0 or view.len.usize().i64() != view.len) implies result == 0.usize()) "
    "and ((view.len > 0 and view.len.usize().i64() == view.len) implies result.i64() == view.len)"
)
if compact(normalization_contract) not in sview_len:
    raise SystemExit("sview_len lost its zero-normalization or representable-length contract")

required_steps = (
    "0.usize() return if view.len <= 0",
    "view_len: usize = view.len.usize()",
    "return 0.usize() if view_len.i64() != view.len",
    "return view_len",
)
step_positions = [sview_len.find(compact(step)) for step in required_steps]
if any(position < 0 for position in step_positions) or step_positions != sorted(step_positions):
    raise SystemExit("sview_len no longer normalizes nonpositive and nonroundtripping lengths before return")

positive_names = {
    "sview_len_obeys_its_piecewise_normalization_contract",
    "a_positive_representable_length_is_preserved",
    "a_nonpositive_length_is_normalized_to_zero",
    "a_nonroundtripping_length_is_normalized_to_zero",
}
negative_names = {
    "a_positive_representable_length_can_become_zero",
    "a_nonpositive_length_can_produce_a_nonzero_result",
}
claims = {
    "sview_len_obeys_its_piecewise_normalization_contract":
        "((view.len <= 0 or view.len.usize().i64() != view.len) implies normalized == 0.usize()) and ((view.len > 0 and view.len.usize().i64() == view.len) implies normalized.i64() == view.len)",
    "a_positive_representable_length_is_preserved":
        "sview_len(view).i64() == view.len",
    "a_nonpositive_length_is_normalized_to_zero":
        "sview_len(view) == 0.usize()",
    "a_nonroundtripping_length_is_normalized_to_zero":
        "sview_len(view) == 0.usize()",
    "a_positive_representable_length_can_become_zero":
        "sview_len(view) == 0.usize()",
    "a_nonpositive_length_can_produce_a_nonzero_result":
        "sview_len(view) != 0.usize()",
}
preconditions = {
    "a_positive_representable_length_is_preserved":
        "requires view.len > 0 and view.len.usize().i64() == view.len",
    "a_nonpositive_length_is_normalized_to_zero": "requires view.len <= 0",
    "a_nonroundtripping_length_is_normalized_to_zero":
        "requires view.len.usize().i64() != view.len",
    "a_positive_representable_length_can_become_zero":
        "requires view.len > 0 and view.len.usize().i64() == view.len",
    "a_nonpositive_length_can_produce_a_nonzero_result": "requires view.len <= 0",
}
for source_text, names, label in (
    (POSITIVE.read_text(), positive_names, "positive"),
    (NEGATIVE.read_text(), negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} sview_len theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text:
        raise SystemExit(f"{label} sview_len theorem no longer includes the production runtime")
    for name in names:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section \
                or compact(claims[name]) not in section \
                or compact("sview_len(view)") not in section:
            raise SystemExit(f"{label} sview_len theorem {name} lost its claim")
        if name in preconditions and compact(preconditions[name]) not in section:
            raise SystemExit(f"{label} sview_len theorem {name} lost its precondition")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("sview_len normalization proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", RUNTIME, POSITIVE, NEGATIVE, *source_closure,
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "sview_len preserves valid positive lengths and maps nonpositive or nonroundtripping lengths to zero",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
