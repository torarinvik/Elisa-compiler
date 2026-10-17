"""Admit source-linked proofs that lexical path cleaning preserves rooted paths."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "project_path_clean.elisa"
NEGATIVE = HERE / "project_path_clean_rejected.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
PATHS = ROOT / "src/driver/project_paths.elisa"

POSITIVE_NAMES = {
    "cleaning_an_absolute_path_preserves_its_root_separator",
    "the_cleaned_absolute_path_remains_absolute",
    "an_empty_relative_path_cleans_to_a_single_dot",
    "a_single_root_separator_cleans_to_itself",
}
NEGATIVE_NAMES = {
    "a_cleaned_absolute_path_can_lose_its_root",
    "an_empty_relative_path_can_clean_to_empty",
    "a_single_root_separator_can_clean_to_dot",
}

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


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


path_text = PATHS.read_text()
project_text = PROJECT.read_text()
cleaner = compact(function_section(path_text, "path_clean"))
root_contract = compact("""
    ensure (path.count > 0.usize() and path[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH) implies (
        result.count > 0.usize() and
        result[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH
    )
""")
if root_contract not in cleaner:
    raise SystemExit("production path_clean no longer specifies root preservation with a bounds guard")
empty_path_contract = compact("""
    ensure (path.count == 0.usize()) implies (
        result.count == 1.usize() and
        result[0.usize()] == 46
    )
""")
if empty_path_contract not in cleaner:
    raise SystemExit("production path_clean no longer specifies the empty-relative-path dot result")
root_only_contract = compact("""
    ensure (path.count == 1.usize() and path[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH) implies (
        result.count == 1.usize() and
        result[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH
    )
""")
if root_only_contract not in cleaner:
    raise SystemExit("production path_clean no longer specifies exact cleaning of the root-only path")
output_start = compact("body: mutable darray[u8] = []")
fallback_start = compact("if out.count == 0.usize():")
if output_start not in cleaner or fallback_start not in cleaner:
    raise SystemExit("production path_clean output construction or empty-relative fallback is missing")
build = cleaner.split(output_start, 1)[1].split(fallback_start, 1)[0]
expected_build = compact("""
    for segment in 0..<depth |body, starts, lengths, path|:
        body.push(47) if segment > 0.usize()
        for offset in 0..<lengths[segment] |body, starts, lengths, path, segment|:
            body.push(path[starts[segment] + offset])
    out: mutable darray[u8] = []
    if path.count > 0.usize() and path[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH:
        out.push(ProjectSystemPathByte::ASCII_FORWARD_SLASH)
    for index in 0..<body.count |out, body, path|:
        invariant not (path.count > 0.usize() and path[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH) or (
            out.count > 0.usize() and
            out[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH
        )
        out.push(body[index])
""")
if build != expected_build:
    raise SystemExit("path_clean root-preserving output loops changed or gained a root-mutating operation")
if compact("if out.count == 0.usize(): out.push(46) return out") not in cleaner:
    raise SystemExit("path_clean no longer uses the relative empty-path fallback")
for fragment in (
    'include "./project_paths.elisa"',
    "path_clean(path) return if path_is_absolute(path)",
    "return path_clean(joined)",
):
    if compact(fragment) not in compact(project_text + path_text):
        raise SystemExit(f"production path-clean call path changed: {fragment}")

positive = POSITIVE.read_text()
negative = NEGATIVE.read_text()
if 'include "../../src/driver/project.elisa"' not in positive or 'include "../../src/driver/project.elisa"' not in negative:
    raise SystemExit("root-preservation proofs no longer include the production project system")
for name, fragments in (
    ("cleaning_an_absolute_path_preserves_its_root_separator", (
        "requires ProjectSystem::path_is_absolute(path)",
        "ProjectSystem::path_clean(path)",
        "cleaned.count > 0.usize()",
        "cleaned[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH",
    )),
    ("the_cleaned_absolute_path_remains_absolute", (
        "requires ProjectSystem::path_is_absolute(path)",
        "ProjectSystem::path_is_absolute(cleaned)",
    )),
):
    body = compact(function_section(positive, name))
    if "ensureresult==true" not in body or any(compact(fragment) not in body for fragment in fragments):
        raise SystemExit(f"rooted path positive proof changed: {name}")
empty_positive = compact(function_section(positive, "an_empty_relative_path_cleans_to_a_single_dot"))
if any(compact(fragment) not in empty_positive for fragment in (
        "requires path.count == 0.usize()",
        "ensure result == true",
        "ProjectSystem::path_clean(path)",
        "cleaned.count == 1.usize() and cleaned[0.usize()] == 46",
)):
    raise SystemExit("empty-path positive proof no longer checks the single-dot fallback")
root_positive = compact(function_section(positive, "a_single_root_separator_cleans_to_itself"))
if any(compact(fragment) not in root_positive for fragment in (
        "requires path.count == 1.usize() and path[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH",
        "ensure result == true",
        "ProjectSystem::path_clean(path)",
        "cleaned.count == 1.usize() and cleaned[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH",
)):
    raise SystemExit("root-only positive proof no longer checks exact slash normalization")
if declarations(POSITIVE) != POSITIVE_NAMES:
    raise SystemExit("project path clean positive proof inventory changed")
if declarations(NEGATIVE) != NEGATIVE_NAMES or 'include "../../src/driver/project.elisa"' not in negative:
    raise SystemExit("project path clean false-claim inventory changed")
negative_body = compact(function_section(negative, "a_cleaned_absolute_path_can_lose_its_root"))
if "ensureresult==true" not in negative_body or "cleaned.count==0.usize()orcleaned[0.usize()]!=ProjectSystemPathByte::ASCII_FORWARD_SLASH" not in negative_body:
    raise SystemExit("rooted path false claim no longer targets an empty or non-rooted result")
empty_negative = compact(function_section(negative, "an_empty_relative_path_can_clean_to_empty"))
if any(compact(fragment) not in empty_negative for fragment in (
        "requires path.count == 0.usize()",
        "ensure result == true",
        "ProjectSystem::path_clean(path)",
        "return cleaned.count == 0.usize()",
)):
    raise SystemExit("empty-path rejected proof no longer challenges the dot fallback")
root_negative = compact(function_section(negative, "a_single_root_separator_can_clean_to_dot"))
if any(compact(fragment) not in root_negative for fragment in (
        "requires path.count == 1.usize() and path[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH",
        "ensure result == true",
        "ProjectSystem::path_clean(path)",
        "return cleaned.count == 1.usize() and cleaned[0.usize()] == 46",
)):
    raise SystemExit("root-only rejected proof no longer challenges exact slash normalization")

# Ensure both path normalization and its callers remain in this proof's exact include closure.
if 'include "./project_paths.elisa"' not in project_text:
    raise SystemExit("ProjectSystem no longer includes the production path implementation")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project path clean proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", PROJECT, PATHS,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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


code, positive_report = run(POSITIVE)
assert code == 0 and positive_report["status"] == positive_report["verification_state"] == "proved"
assert positive_report["summary"]["proven"] == positive_report["summary"]["obligations"]
assert not positive_report["findings"]
assert positive_report == run(POSITIVE)[1], "project path clean report changed across repeated runs"
verified = {row["name"] for row in positive_report["declaration_details"] if row.get("verified")}
assert (POSITIVE_NAMES | {"path_clean", "path_is_absolute"}) <= verified

code, negative_report = run(NEGATIVE)
assert code == 1 and negative_report["status"] == negative_report["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative_report["findings"]} == {
    ("ensure-unproven", "a_cleaned_absolute_path_can_lose_its_root"),
    ("ensure-unproven", "an_empty_relative_path_can_clean_to_empty"),
    ("ensure-unproven", "a_single_root_separator_can_clean_to_dot"),
}
negative_verified = {row["name"] for row in negative_report["declaration_details"] if row.get("verified")}
assert {"path_clean", "path_is_absolute"} <= negative_verified
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "project path clean proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "root preservation and the empty-relative fallback in the production lexical path cleaner",
    "positive_obligations": positive_report["summary"]["proven"],
    "false_claim_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
