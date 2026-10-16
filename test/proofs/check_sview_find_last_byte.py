"""Bind reverse StringView search proofs to its scan invariant and contracts."""
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
POSITIVE = HERE / "sview_find_last_byte.elisa"
NEGATIVE = HERE / "sview_find_last_byte_rejected.elisa"

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
reverse_search = compact(function_section(runtime_text, "sview_find_last_byte"))
required_contract = (
    "ensure ((view.len < 0 or view.len.usize().i64() != view.len) implies result == -1) "
    "and result >= -1 and (result >= 0 implies result < view.len "
    "and string_view_index(view, result) == byte.i64() "
    "and (forall later in result + 1..<view.len: string_view_index(view, later) != byte.i64())) "
    "and ((view.len >= 0 and view.len.usize().i64() == view.len and result == -1) implies "
    "(forall candidate in 0..<view.len: string_view_index(view, candidate) != byte.i64()))"
)
if compact(required_contract) not in reverse_search:
    raise SystemExit("reverse byte search lost its sentinel, match, maximality, or absence contract")

filename = compact(function_section(runtime_text, "filename"))
required_filename_contract = (
    "ensure (p.len >= 0 and p.len.usize().i64() == p.len) implies "
    "(result.len == p.len - (sview_find_last_byte(p, 47) + 1) "
    "and (result.len == 0 or result.data == p.data + (sview_find_last_byte(p, 47) + 1).usize()))"
)
if compact(required_filename_contract) not in filename \
        or compact("return string_view_suffix(p, slash + 1)") not in filename:
    raise SystemExit("Fs.filename lost its last-separator suffix length or backing offset")

parent = compact(function_section(runtime_text, "parent"))
required_parent_contract = (
    "ensure (p.len >= 0 and p.len.usize().i64() == p.len) implies "
    "((sview_find_last_byte(p, 47) >= 0 and result.len == sview_find_last_byte(p, 47) "
    "and (result.len == 0 or result.data == p.data)) "
    "or (sview_find_last_byte(p, 47) == -1 and result.len == 0))"
)
if compact(required_parent_contract) not in parent \
        or compact('return string_view_prefix(p, slash) if slash >= 0 else sview("", 0, 0)') not in parent:
    raise SystemExit("Fs.parent lost its pre-separator prefix or no-separator empty-view contract")

required_loop_steps = (
    "return -1 if view.len < 0",
    "view_len: usize = view.len.usize()",
    "return -1 if view_len.i64() != view.len",
    "assert view.len >= 0 and view_len.i64() == view.len",
    "i: mutable i64 = view.len",
    "while i > 0:",
    "decreases i",
    "invariant 0 <= i and i <= view.len",
    "invariant forall later in i..<view.len: string_view_index(view, later) != byte.i64()",
    "candidate: i64 = i - 1",
    "return candidate if string_view_index(view, candidate) == byte.i64()",
    "i <- candidate",
    "return -1",
)
loop_positions = []
search_offset = 0
for step in required_loop_steps:
    position = reverse_search.find(compact(step), search_offset)
    loop_positions.append(position)
    if position >= 0:
        search_offset = position + len(compact(step))
if any(position < 0 for position in loop_positions) or loop_positions != sorted(loop_positions):
    raise SystemExit("reverse search loop lost its decreasing bound, searched-suffix invariant, or result step")

positive_names = {
    "reverse_search_obeys_its_last_match_contract",
    "a_found_reverse_search_result_is_the_last_matching_offset",
    "an_absent_reverse_search_result_means_no_match",
    "an_unrepresentable_reverse_search_length_returns_minus_one",
    "filename_is_the_suffix_after_the_last_slash",
    "parent_is_the_prefix_before_the_last_slash",
}
negative_names = {
    "reverse_search_can_return_an_earlier_match",
    "reverse_search_can_miss_a_known_matching_offset",
    "filename_can_keep_a_slash_in_its_extent",
    "parent_can_extend_past_the_last_slash",
}
claims = {
    "reverse_search_obeys_its_last_match_contract": (
        "((view.len < 0 or view.len.usize().i64() != view.len) implies found == -1) "
        "and found >= -1 and (found >= 0 implies (found < view.len "
        "and string_view_index(view, found) == byte.i64() "
        "and (forall later in found + 1..<view.len: string_view_index(view, later) != byte.i64()))) "
        "and ((view.len >= 0 and view.len.usize().i64() == view.len and found == -1) implies "
        "(forall candidate in 0..<view.len: string_view_index(view, candidate) != byte.i64()))"
    ),
    "a_found_reverse_search_result_is_the_last_matching_offset": (
        "found < view.len and string_view_index(view, found) == byte.i64() "
        "and (forall later in found + 1..<view.len: string_view_index(view, later) != byte.i64())"
    ),
    "an_absent_reverse_search_result_means_no_match": (
        "forall candidate in 0..<view.len: string_view_index(view, candidate) != byte.i64()"
    ),
    "an_unrepresentable_reverse_search_length_returns_minus_one":
        "sview_find_last_byte(view, byte) == -1",
    "reverse_search_can_return_an_earlier_match":
        "sview_find_last_byte(view, byte) == earlier",
    "reverse_search_can_miss_a_known_matching_offset":
        "sview_find_last_byte(view, byte) == -1",
    "filename_is_the_suffix_after_the_last_slash": (
        "slash >= -1 and slash < path.len and name.len == path.len - start "
        "and (name.len == 0 or name.data == path.data + start.usize())"
    ),
    "parent_is_the_prefix_before_the_last_slash": (
        "(slash >= 0 and parent.len == slash and (parent.len == 0 or parent.data == path.data)) "
        "or (slash == -1 and parent.len == 0)"
    ),
    "filename_can_keep_a_slash_in_its_extent": "Fs::filename(path).len == path.len",
    "parent_can_extend_past_the_last_slash": "Fs::parent(path).len > sview_find_last_byte(path, 47)",
}
preconditions = {
    "a_found_reverse_search_result_is_the_last_matching_offset": (
        "requires view.len >= 0 and view.len.usize().i64() == view.len "
        "requires sview_find_last_byte(view, byte) >= 0"
    ),
    "an_absent_reverse_search_result_means_no_match": (
        "requires view.len >= 0 and view.len.usize().i64() == view.len "
        "requires sview_find_last_byte(view, byte) == -1"
    ),
    "an_unrepresentable_reverse_search_length_returns_minus_one":
        "requires view.len < 0 or view.len.usize().i64() != view.len",
    "reverse_search_can_return_an_earlier_match": (
        "requires view.len >= 0 and view.len.usize().i64() == view.len "
        "requires earlier >= 0 and earlier < later and later < view.len "
        "requires string_view_index(view, earlier) == byte.i64() "
        "requires string_view_index(view, later) == byte.i64()"
    ),
    "reverse_search_can_miss_a_known_matching_offset": (
        "requires view.len >= 0 and view.len.usize().i64() == view.len "
        "requires candidate >= 0 and candidate < view.len "
        "requires string_view_index(view, candidate) == byte.i64()"
    ),
    "filename_is_the_suffix_after_the_last_slash":
        "requires path.len >= 0 and path.len.usize().i64() == path.len",
    "parent_is_the_prefix_before_the_last_slash":
        "requires path.len >= 0 and path.len.usize().i64() == path.len",
    "filename_can_keep_a_slash_in_its_extent": (
        "requires path.len >= 0 and path.len.usize().i64() == path.len "
        "requires sview_find_last_byte(path, 47) >= 0"
    ),
    "parent_can_extend_past_the_last_slash": (
        "requires path.len >= 0 and path.len.usize().i64() == path.len "
        "requires sview_find_last_byte(path, 47) >= 0"
    ),
}
bindings = {
    name: ("sview_find_last_byte(view, byte)",)
    for name in positive_names | negative_names
    if not name.startswith("filename_") and not name.startswith("parent_")
}
bindings.update({
    "filename_is_the_suffix_after_the_last_slash": (
        "sview_find_last_byte(path, 47)", "Fs::filename(path)"),
    "parent_is_the_prefix_before_the_last_slash": (
        "sview_find_last_byte(path, 47)", "Fs::parent(path)"),
    "filename_can_keep_a_slash_in_its_extent": (
        "sview_find_last_byte(path, 47)", "Fs::filename(path)"),
    "parent_can_extend_past_the_last_slash": (
        "sview_find_last_byte(path, 47)", "Fs::parent(path)"),
})
for source_text, names, label in (
    (POSITIVE.read_text(), positive_names, "positive"),
    (NEGATIVE.read_text(), negative_names, "negative"),
):
    if declarations(source_text) != names:
        raise SystemExit(f"{label} reverse byte-search theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source_text \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source_text:
        raise SystemExit(f"{label} reverse byte-search theorem no longer includes the production runtime")
    for name in names:
        section = compact(function_section(source_text, name))
        if compact("ensure result == true") not in section \
                or compact(claims[name]) not in section:
            raise SystemExit(f"{label} reverse byte-search theorem {name} lost its claim")
        if name in preconditions and compact(preconditions[name]) not in section:
            raise SystemExit(f"{label} reverse byte-search theorem {name} lost its precondition")
        if any(compact(binding) not in section for binding in bindings[name]):
            raise SystemExit(f"{label} reverse byte-search theorem {name} lost its runtime binding")

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
    raise SystemExit("reverse StringView byte-search proofs require a strict proof build")

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
    "scope": "reverse search returns the last matching byte index or -1, and fails closed for invalid lengths",
    "positive_claims_proved": sorted(positive_names),
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
