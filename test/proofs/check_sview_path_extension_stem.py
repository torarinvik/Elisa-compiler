"""Bind path extension/stem proofs to the production StringView helpers."""
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
PATH_VIEWS = ROOT / "elisacore_std/elisacore_runtime_string_path_views.elisa"
POSITIVE = HERE / "sview_path_extension_stem.elisa"
NEGATIVE = HERE / "sview_path_extension_stem_rejected.elisa"

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
extension = compact(function_section(runtime_text, "extension"))
stem = compact(function_section(runtime_text, "stem"))
valid = "p.len >= 0 and p.len.usize().i64() == p.len"
invalid = "p.len < 0 or p.len.usize().i64() != p.len"
path_valid = "path.len >= 0 and path.len.usize().i64() == path.len"
path_invalid = "path.len < 0 or path.len.usize().i64() != path.len"
dot_after_name = "sview_find_last_byte(p, 46) > sview_find_last_byte(p, 47) + 1"
dot_not_after_name = "sview_find_last_byte(p, 46) <= sview_find_last_byte(p, 47) + 1"
extension_contracts = (
    f"ensure ({invalid}) implies result.len == 0",
    f"ensure ({valid} and {dot_after_name}) implies result.len == p.len - sview_find_last_byte(p, 46)",
    f"ensure ({valid} and {dot_not_after_name}) implies result.len == 0",
    f"ensure ({valid} and {dot_after_name}) implies result.data == p.data + sview_find_last_byte(p, 46).usize()",
)
stem_contracts = (
    f"ensure ({invalid}) implies result.len == 0",
    f"ensure ({valid} and {dot_after_name}) implies result.len == sview_find_last_byte(p, 46) - (sview_find_last_byte(p, 47) + 1)",
    f"ensure ({valid} and {dot_not_after_name}) implies result.len == p.len - (sview_find_last_byte(p, 47) + 1)",
    f"ensure ({valid} and sview_find_last_byte(p, 47) >= 0) implies result.data == p.data + (sview_find_last_byte(p, 47) + 1).usize()",
    f"ensure ({valid} and sview_find_last_byte(p, 47) == -1) implies result.data == p.data",
)
if any(compact(contract) not in extension for contract in extension_contracts):
    raise SystemExit("Fs::extension lost its malformed-input, last-dot, offset, or byte-preservation contract")
if any(compact(contract) not in stem for contract in stem_contracts):
    raise SystemExit("Fs::stem lost its malformed-input, basename, offset, or byte-preservation contract")
if compact('return string_view_empty_at(p.data) if p.len < 0 or p.len.usize().i64() != p.len') not in extension \
        or compact("slash: i64 = sview_find_last_byte(p, 47)") not in extension \
        or compact("name_start: i64 = slash + 1") not in extension \
        or compact("dot: i64 = sview_find_last_byte(p, 46)") not in extension \
        or compact("assert slash >= -1 and slash < p.len") not in extension \
        or compact("assert name_start >= 0 and name_start <= p.len") not in extension \
        or compact("assert dot >= -1 and dot < p.len") not in extension \
        or compact("if dot > name_start: trusted Unsafe.PointerCast: return StringView{data: p.data + dot.usize(), len: p.len - dot}") not in extension \
        or compact("assert dot <= name_start") not in extension \
        or compact('return StringView{data: p.data, len: 0}') not in extension:
    raise SystemExit("Fs::extension no longer returns the final qualifying dot suffix")
if compact('return string_view_empty_at(p.data) if p.len < 0 or p.len.usize().i64() != p.len') not in stem \
        or compact("slash: i64 = sview_find_last_byte(p, 47)") not in stem \
        or compact("name_start: i64 = slash + 1") not in stem \
        or compact("dot: i64 = sview_find_last_byte(p, 46)") not in stem \
        or compact("assert slash >= -1 and slash < p.len") not in stem \
        or compact("assert slash == sview_find_last_byte(p, 47)") not in stem \
        or compact("assert dot == sview_find_last_byte(p, 46)") not in stem \
        or compact("assert name_start >= 0 and name_start <= p.len") not in stem \
        or compact("assert dot >= -1 and dot < p.len") not in stem \
        or compact("if dot > name_start: if slash >= 0: trusted Unsafe.PointerCast: return StringView{data: p.data + (slash + 1).usize(), len: dot - name_start}") not in stem \
        or compact("assert slash == -1") not in stem \
        or compact("trusted Unsafe.PointerCast: return StringView{data: p.data, len: dot - name_start}") not in stem \
        or compact("if slash >= 0: trusted Unsafe.PointerCast: return StringView{data: p.data + (slash + 1).usize(), len: p.len - name_start}") not in stem \
        or compact("trusted Unsafe.PointerCast: return StringView{data: p.data, len: p.len - name_start}") not in stem:
    raise SystemExit("Fs::stem no longer cuts before the final qualifying dot")

positive_claims = {
    "extension_preserves_the_last_dot_suffix": "extension.len == path.len - dot and extension.data == path.data + dot.usize()",
    "extension_is_empty_without_a_dot_after_the_basename_start": "Fs::extension(path).len == 0",
    "stem_preserves_the_prefix_before_the_last_dot": "stem.len == dot - (slash + 1) and stem.data == path.data + (slash + 1).usize()",
    "stem_is_the_full_basename_without_a_qualifying_dot": "stem.len == path.len - (slash + 1) and stem.data == path.data + (slash + 1).usize()",
    "malformed_path_extension_and_stem_are_empty": "Fs::extension(path).len == 0 and Fs::stem(path).len == 0",
    "a_leading_dot_is_part_of_a_hidden_file_stem": "extension.len == 0 and stem.len == 4 and string_view_index(stem, 0) == 46",
    "a_trailing_dot_is_a_one_byte_extension": "extension.len == 1 and string_view_index(extension, 0) == 46 and stem.len == 4",
    "a_directory_dot_does_not_define_the_file_extension": "extension.len == 0 and stem.len == 4",
}
positive_requires = {
    "extension_preserves_the_last_dot_suffix": f"requires {path_valid} requires sview_find_last_byte(path, 46) > sview_find_last_byte(path, 47) + 1",
    "extension_is_empty_without_a_dot_after_the_basename_start": f"requires {path_valid} requires sview_find_last_byte(path, 46) <= sview_find_last_byte(path, 47) + 1",
    "stem_preserves_the_prefix_before_the_last_dot": f"requires {path_valid} requires sview_find_last_byte(path, 46) > sview_find_last_byte(path, 47) + 1",
    "stem_is_the_full_basename_without_a_qualifying_dot": f"requires {path_valid} requires sview_find_last_byte(path, 46) <= sview_find_last_byte(path, 47) + 1",
    "malformed_path_extension_and_stem_are_empty": f"requires {path_invalid}",
}
negative_claims = {
    "a_path_without_a_qualifying_dot_can_have_a_nonempty_extension": "Fs::extension(path).len != 0",
    "a_qualifying_extension_can_omit_the_dot": "Fs::extension(path).len == path.len - sview_find_last_byte(path, 46) - 1",
    "a_stem_can_include_the_final_dot": "Fs::stem(path).len > sview_find_last_byte(path, 46) - (sview_find_last_byte(path, 47) + 1)",
    "a_malformed_path_can_have_a_nonempty_stem_or_extension": "Fs::stem(path).len != 0 or Fs::extension(path).len != 0",
}
negative_requires = {
    "a_path_without_a_qualifying_dot_can_have_a_nonempty_extension": f"requires {path_valid} requires sview_find_last_byte(path, 46) <= sview_find_last_byte(path, 47) + 1",
    "a_qualifying_extension_can_omit_the_dot": f"requires {path_valid} requires sview_find_last_byte(path, 46) > sview_find_last_byte(path, 47) + 1",
    "a_stem_can_include_the_final_dot": f"requires {path_valid} requires sview_find_last_byte(path, 46) > sview_find_last_byte(path, 47) + 1",
    "a_malformed_path_can_have_a_nonempty_stem_or_extension": f"requires {path_invalid}",
}
for path, claims, preconditions, label in (
    (POSITIVE, positive_claims, positive_requires, "positive"),
    (NEGATIVE, negative_claims, negative_requires, "negative"),
):
    source = path.read_text()
    if declarations(source) != set(claims):
        raise SystemExit(f"{label} path extension/stem theorem inventory changed")
    if 'include "../../elisacore_std/elisacore_runtime_prelude.elisa"' not in source \
            or 'include "../../elisacore_std/elisacore_runtime_strings.elisa"' not in source:
        raise SystemExit(f"{label} path theorem no longer includes the production runtime")
    for name, claim in claims.items():
        section = compact(function_section(source, name))
        if compact("ensure result == true") not in section \
                or compact(claim) not in section \
                or (name in preconditions and compact(preconditions[name]) not in section):
            raise SystemExit(f"{label} path theorem {name} lost its claim or precondition")
        if "Fs::extension(path)" not in section and "Fs::stem(path)" not in section:
            raise SystemExit(f"{label} path theorem {name} is no longer bound to the production helpers")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if PATH_VIEWS not in source_closure:
    raise SystemExit("proof include closure no longer contains the production path helper module")
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
    raise SystemExit("path extension/stem proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", RUNTIME, PATH_VIEWS, POSITIVE, NEGATIVE, *source_closure,
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
    "scope": "extension and stem refine last-dot path-component semantics, preserve offsets and bytes, and fail closed for malformed extents",
    "positive_claims_proved": sorted(positive_claims),
    "false_claims_refused": sorted(negative_claims),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
