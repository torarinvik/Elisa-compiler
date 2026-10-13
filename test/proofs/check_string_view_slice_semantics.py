"""Bind the StringView slice refinement theorem to the runtime implementation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
RUNTIME = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
POSITIVE = HERE / "string_view_slice_semantics.elisa"
NEGATIVE = HERE / "string_view_slice_semantics_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


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
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
slice_body = compact(function_section(runtime_text, "string_view_slice"))
required_slice_steps = (
    'empty:sview=sview("",0,0)',
    "emptyreturnifview.len<0",
    "emptyreturnifview.len==0",
    "view_len:usize=view.len.usize()",
    "returnemptyifview_len.i64()!=view.len",
    "lo:mutablei64=startifstart>0else0",
    "hi:mutablei64=endifend>=0elseview.len",
    "lo<-view.leniflo>view.len",
    "hi<-view.lenifhi>view.len",
    "hi<-loifhi<lo",
    "trustedUnsafe.PointerCast:returnStringView{data:view.data+lo.usize(),len:hi-lo}",
)
slice_positions = [slice_body.find(step) for step in required_slice_steps]
if any(position < 0 for position in slice_positions) or slice_positions != sorted(slice_positions):
    raise SystemExit("StringView slice lost its ordered length validation, clamping, or bounded pointer construction")
prefix_body = compact(function_section(runtime_text, "string_view_prefix"))
suffix_body = compact(function_section(runtime_text, "string_view_suffix"))
if "returnstring_view_slice(view,0,end)" not in prefix_body:
    raise SystemExit("StringView prefix no longer delegates with a zero start and requested end")
if "returnstring_view_slice(view,start,view.len)" not in suffix_body:
    raise SystemExit("StringView suffix no longer delegates with the requested start and view length")

model_texts = (
    compact(function_section(positive_text, "string_view_slice_bounds")),
    compact(function_section(negative_text, "string_view_slice_bounds")),
)
required_model_steps = (
    "requireslength>=0",
    "ensureresult.low==(startifstart>0andstart<=lengthelselengthifstart>lengthelse0)",
    "ensureresult.high==(lengthifend<0elseresult.lowifend<result.lowelseendifend<=lengthelselength)",
    "ensureresult.low>=0andresult.low<=length",
    "ensureresult.high>=result.lowandresult.high<=length",
    "low:mutablei64=startifstart>0else0",
    "high:mutablei64=endifend>=0elselength",
    "low<-lengthiflow>length",
    "high<-lengthifhigh>length",
    "high<-lowifhigh<low",
    "return(low,high)",
)
if any(any(step not in model for step in required_model_steps) for model in model_texts):
    raise SystemExit("slice reference model lost a bound, default-end, clamp, or ordering law")

positive_claims = {
    "a_runtime_slice_has_the_specified_clamped_extent": (
        "sliced.len == bounds.high - bounds.low and (sliced.len == 0 or sliced.data == view.data + bounds.low.usize())",
        "string_view_slice(view, start, end)",
    ),
    "a_runtime_prefix_has_the_specified_clamped_extent": (
        "prefix.len == bounds.high - bounds.low and (prefix.len == 0 or prefix.data == view.data)",
        "string_view_prefix(view, end)",
    ),
    "a_runtime_suffix_has_the_specified_clamped_extent": (
        "suffix.len == bounds.high - bounds.low and (suffix.len == 0 or suffix.data == view.data + bounds.low.usize())",
        "string_view_suffix(view, start)",
    ),
}
negative_claims = {
    "a_runtime_slice_can_disagree_with_its_clamped_extent": (
        "sliced.len != bounds.high - bounds.low",
        "string_view_slice(view, start, end)",
    ),
    "a_runtime_prefix_can_disagree_with_its_clamped_extent": (
        "prefix.len != bounds.high - bounds.low",
        "string_view_prefix(view, end)",
    ),
    "a_runtime_suffix_can_disagree_with_its_clamped_extent": (
        "suffix.len != bounds.high - bounds.low",
        "string_view_suffix(view, start)",
    ),
    "a_runtime_slice_can_return_a_different_backing_offset": (
        "sliced.len > 0 and sliced.data != view.data + bounds.low.usize()",
        "string_view_slice(view, start, end)",
    ),
    "a_runtime_prefix_can_return_a_different_backing_offset": (
        "prefix.len > 0 and prefix.data != view.data",
        "string_view_prefix(view, end)",
    ),
    "a_runtime_suffix_can_return_a_different_backing_offset": (
        "suffix.len > 0 and suffix.data != view.data + bounds.low.usize()",
        "string_view_suffix(view, start)",
    ),
}
positive_names = set(positive_claims)
negative_names = set(negative_claims)
precondition = "requires view.len >= 0 and view.len.usize().i64() == view.len"
for source_text, claims, label in (
    (positive_text, positive_claims, "positive"),
    (negative_text, negative_claims, "negative"),
):
    names = set(claims)
    if declarations(source_text) != names:
        raise SystemExit(f"{label} StringView slice theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text:
        raise SystemExit(f"{label} StringView slice theorem no longer includes the runtime source")
    for name, (claim, production_call) in claims.items():
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section or compact(precondition) not in section \
                or compact(claim) not in section or compact(production_call) not in section:
            raise SystemExit(f"{label} StringView theorem {name} lost its production call or exact claim")

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
    raise SystemExit("StringView slice proofs require a strict proof build")

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
    "scope": "StringView slice length equals the clamped half-open interval length",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
