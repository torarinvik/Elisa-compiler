"""Bind basename and dirname proofs to the production StringView helpers."""
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
PRELUDE = ROOT / "elisacore_std/elisacore_runtime_prelude.elisa"
RUNTIME = ROOT / "elisacore_std/elisacore_runtime_strings.elisa"
PATH_VIEWS = ROOT / "elisacore_std/elisacore_runtime_string_path_views.elisa"
POSITIVE = HERE / "sview_path_views.elisa"
NEGATIVE = HERE / "sview_path_views_rejected.elisa"

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
path_text = PATH_VIEWS.read_text()
if compact('include "./elisacore_runtime_string_path_views.elisa"') not in compact(runtime_text):
    raise SystemExit("runtime strings no longer includes the specified path-view helpers")

search = compact(function_section(runtime_text, "sview_find_last_byte"))
search_contract = (
    "ensure ((view.len < 0 or view.len.usize().i64() != view.len) implies result == -1) "
    "and result >= -1 and (result >= 0 implies result < view.len "
    "and string_view_index(view, result) == byte.i64() "
    "and (forall later in result + 1..<view.len: string_view_index(view, later) != byte.i64())) "
    "and ((view.len >= 0 and view.len.usize().i64() == view.len and result == -1) implies "
    "(forall candidate in 0..<view.len: string_view_index(view, candidate) != byte.i64()))"
)
if compact(search_contract) not in search:
    raise SystemExit("path-view proofs no longer have a last-match, maximality, and absence contract")

valid_extent = "view.len >= 0 and view.len.usize().i64() == view.len"
invalid_extent = "view.len < 0 or view.len.usize().i64() != view.len"
basename = compact(function_section(path_text, "sview_basename"))
dirname = compact(function_section(path_text, "sview_dirname"))
required_basename_contracts = (
    f"(({invalid_extent}) implies result.len == 0)",
    f"(({valid_extent} and sview_find_last_byte(view, sep) >= 0) implies result.len == view.len - (sview_find_last_byte(view, sep) + 1))",
    f"(({valid_extent} and sview_find_last_byte(view, sep) == -1) implies result.len == view.len)",
    f"ensure ({valid_extent} and sview_find_last_byte(view, sep) >= 0 and result.len > 0) implies result.data == view.data + (sview_find_last_byte(view, sep) + 1).usize()",
    f"ensure ({valid_extent} and sview_find_last_byte(view, sep) == -1 and result.len > 0) implies result.data == view.data",
    f"ensure ({valid_extent} and sview_find_last_byte(view, sep) >= 0) implies (forall offset in 0..<result.len: string_view_index(result, offset) == string_view_index(view, sview_find_last_byte(view, sep) + 1 + offset))",
    f"ensure ({valid_extent} and sview_find_last_byte(view, sep) == -1) implies (forall offset in 0..<result.len: string_view_index(result, offset) == string_view_index(view, offset))",
)
required_dirname_contracts = (
    f"(({invalid_extent}) implies result.len == 0)",
    f"(({valid_extent} and sview_find_last_byte(view, sep) >= 0) implies result.len == sview_find_last_byte(view, sep))",
    f"(({valid_extent} and sview_find_last_byte(view, sep) == -1) implies result.len == 0)",
    f"ensure ({valid_extent} and sview_find_last_byte(view, sep) >= 0 and result.len > 0) implies result.data == view.data",
    f"ensure ({valid_extent}) implies (forall offset in 0..<result.len: string_view_index(result, offset) == string_view_index(view, offset))",
)
if any(compact(clause) not in basename for clause in required_basename_contracts):
    raise SystemExit("sview_basename lost its invalid-extent, suffix, backing-offset, or byte-preservation contract")
if any(compact(clause) not in dirname for clause in required_dirname_contracts):
    raise SystemExit("sview_dirname lost its invalid-extent, prefix, backing-offset, or byte-preservation contract")

for helper, fragments, label in (
    (basename, (
        'return "" if view.len < 0 or view.len.usize().i64() != view.len',
        "last: i64 = sview_find_last_byte(view, sep)",
        "return string_view_slice(view, last + 1, view.len) if last >= 0",
        "return view",
    ), "basename"),
    (dirname, (
        'return "" if view.len < 0 or view.len.usize().i64() != view.len',
        "last: i64 = sview_find_last_byte(view, sep)",
        "return string_view_prefix(view, last) if last >= 0",
        "return string_view_prefix(view, 0)",
    ), "dirname"),
):
    body = helper.split("canUnsafe{PointerArithmetic,RawExtern,UncheckedIndex}:", 1)[-1]
    positions = [body.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"sview_{label} no longer normalizes extents and selects its component by the last separator")
    if "while" in body:
        raise SystemExit(f"sview_{label} duplicated a reverse scan instead of using the specified search helper")

positive_names = {
    "basename_has_the_last_separator_extent_and_offset",
    "basename_preserves_the_component_bytes",
    "dirname_has_the_prefix_extent_and_offset",
    "dirname_preserves_the_prefix_bytes",
    "malformed_view_components_have_zero_extent",
}
negative_names = {
    "basename_can_end_with_the_last_separator",
    "dirname_can_extend_through_the_last_separator",
    "malformed_view_can_have_a_nonempty_basename",
    "malformed_view_can_have_a_nonempty_dirname",
}
claims = {
    "basename_has_the_last_separator_extent_and_offset": "(last == -1 and base.len == view.len and (base.len == 0 or base.data == view.data)) or (last >= 0 and base.len == view.len - (last + 1) and (base.len == 0 or base.data == view.data + (last + 1).usize()))",
    "basename_preserves_the_component_bytes": "forall offset in 0..<base.len: string_view_index(base, offset) == string_view_index(view, last + 1 + offset)",
    "dirname_has_the_prefix_extent_and_offset": "(last == -1 and parent.len == 0) or (last >= 0 and parent.len == last and (parent.len == 0 or parent.data == view.data))",
    "dirname_preserves_the_prefix_bytes": "forall offset in 0..<parent.len: string_view_index(parent, offset) == string_view_index(view, offset)",
    "malformed_view_components_have_zero_extent": "sview_basename(view, sep).len == 0 and sview_dirname(view, sep).len == 0",
    "basename_can_end_with_the_last_separator": "string_view_index(base, base.len - 1) == sep.i64()",
    "dirname_can_extend_through_the_last_separator": "sview_dirname(view, sep).len > sview_find_last_byte(view, sep)",
    "malformed_view_can_have_a_nonempty_basename": "sview_basename(view, sep).len != 0",
    "malformed_view_can_have_a_nonempty_dirname": "sview_dirname(view, sep).len != 0",
}
requirements = {
    "basename_has_the_last_separator_extent_and_offset": f"requires {valid_extent}",
    "basename_preserves_the_component_bytes": f"requires {valid_extent}",
    "dirname_has_the_prefix_extent_and_offset": f"requires {valid_extent}",
    "dirname_preserves_the_prefix_bytes": f"requires {valid_extent}",
    "malformed_view_components_have_zero_extent": f"requires {invalid_extent}",
    "basename_can_end_with_the_last_separator": f"requires {valid_extent} requires sview_find_last_byte(view, sep) >= 0 requires sview_find_last_byte(view, sep) + 1 < view.len",
    "dirname_can_extend_through_the_last_separator": f"requires {valid_extent} requires sview_find_last_byte(view, sep) >= 0",
    "malformed_view_can_have_a_nonempty_basename": f"requires {invalid_extent}",
    "malformed_view_can_have_a_nonempty_dirname": f"requires {invalid_extent}",
}
bindings = {
    "basename_has_the_last_separator_extent_and_offset": ("sview_find_last_byte(view, sep)", "sview_basename(view, sep)"),
    "basename_preserves_the_component_bytes": ("sview_find_last_byte(view, sep)", "sview_basename(view, sep)"),
    "dirname_has_the_prefix_extent_and_offset": ("sview_find_last_byte(view, sep)", "sview_dirname(view, sep)"),
    "dirname_preserves_the_prefix_bytes": ("sview_dirname(view, sep)",),
    "malformed_view_components_have_zero_extent": ("sview_basename(view, sep)", "sview_dirname(view, sep)"),
    "basename_can_end_with_the_last_separator": ("sview_find_last_byte(view, sep)", "sview_basename(view, sep)"),
    "dirname_can_extend_through_the_last_separator": ("sview_find_last_byte(view, sep)", "sview_dirname(view, sep)"),
    "malformed_view_can_have_a_nonempty_basename": ("sview_basename(view, sep)",),
    "malformed_view_can_have_a_nonempty_dirname": ("sview_dirname(view, sep)",),
}
for source_text, names, label in (
    (POSITIVE.read_text(), positive_names, "positive"),
    (NEGATIVE.read_text(), negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} path-view theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text:
        raise SystemExit(f"{label} path-view proofs no longer include the production runtime")
    for name in names:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section \
                or compact(claims[name]) not in section \
                or compact(requirements[name]) not in section \
                or any(compact(binding) not in section for binding in bindings[name]):
            raise SystemExit(f"{label} path-view theorem {name} lost its claim, precondition, or production binding")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if PATH_VIEWS not in source_closure:
    raise SystemExit("proof include closure no longer contains the production path-view module")
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
    raise SystemExit("StringView path-component proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", PRELUDE, RUNTIME, PATH_VIEWS,
    POSITIVE, NEGATIVE, *source_closure,
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
    "scope": "StringView basename and dirname preserve the last-separator suffix/prefix, offsets, bytes, and empty-result behavior for malformed extents",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
