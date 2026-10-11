"""Admit source-linked proofs of ProjectSystem's absolute-path boundary."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "project_path_absolute.elisa"
NEGATIVE = HERE / "project_path_absolute_rejected.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
PATHS = ROOT / "src/driver/project_paths.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return " ".join(text.split())


project_text = PROJECT.read_text()
path_text = PATHS.read_text()
driver_text = DRIVER.read_text()
marker = "def path_is_absolute(path: darray[u8]&) -> bool:"
normalized = compact(path_text)
expected = "path.count > 0.usize() and path[0.usize()] == ProjectSystemPathByte::ASCII_FORWARD_SLASH"
if "const module ProjectSystemPathByte: ASCII_FORWARD_SLASH: u8 = 47" not in normalized:
    raise SystemExit("absolute-path separator does not have its canonical named byte constant")
if marker not in normalized:
    raise SystemExit("production absolute-path predicate is missing")
if f"ensure result == ({expected})" not in normalized:
    raise SystemExit("production absolute-path contract no longer states the exact boundary")
if f"return {expected}" not in normalized:
    raise SystemExit("production absolute-path implementation no longer matches its contract")
if 'include "./project_paths.elisa"' not in project_text:
    raise SystemExit("project system no longer imports the proved path predicate")
if 'include "./project.elisa"' not in driver_text:
    raise SystemExit("compiler driver no longer imports the project system")
if "path_clean(path) return if path_is_absolute(path)" not in normalized:
    raise SystemExit("absolute-path resolution no longer uses the proved predicate")
if 'include "../../src/driver/project.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports production project code")
if 'include "../../src/driver/project.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative proof no longer imports production project code")


def include_closure(roots: list[Path]) -> list[Path]:
    include = re.compile(r'^\s*include\s+"([^"]+)"', re.MULTILINE)
    pending = list(roots)
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in seen:
            continue
        seen.add(path)
        for relative in include.findall(path.read_text()):
            child = (path.parent / relative).resolve(strict=True)
            if child not in seen:
                pending.append(child)
    return sorted(seen)


try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project path proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST_CHECKSUM,
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    *[path.resolve(strict=True) for path in (DRIVER, PROJECT, PATHS)],
    *include_closure([POSITIVE, NEGATIVE, PROJECT]),
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
assert positive == run(POSITIVE)[1], "positive proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "path_is_absolute",
    "production_predicate_matches_the_leading_separator_rule",
    "empty_path_is_relative",
    "slash_prefixed_path_is_absolute",
    "non_slash_prefixed_path_is_relative",
} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "empty_path_is_absolute"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
assert subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                      check=True, capture_output=True, text=True).stdout.strip() == compiler_head
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact source-linked project absolute-path predicate",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected": "empty_path_is_absolute",
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
