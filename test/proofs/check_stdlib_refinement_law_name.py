"""Admit source-linked proofs of builtin/stdlib refinement-law name recognition."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "stdlib_refinement_law_name.elisa"
NEGATIVE = HERE / "stdlib_refinement_law_name_rejected.elisa"
HELPER = ROOT / "src/semantic/stdlib_refinement_law_name.elisa"
CONSUMER = ROOT / "src/semantic/check_refinement_is_law.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


if not __debug__:
    raise SystemExit("run without Python -O")

LAW_NAMES = (
    "Aligned", "Divides", "Fits", "MaskedZero", "Nat", "Positive", "StrictlyPositive",
    "NonNeg", "Negative", "NonPositive", "Bounded", "InRange", "Even", "Odd", "NonZero",
    "UpperBound", "LowerBound", "AtMost", "AtLeast", "Finite", "Sorted", "Unique", "NonEmpty",
)
EXPECTED_POSITIVE = {
    "source_classifier_has_exact_law_set",
    "every_builtin_and_stdlib_law_is_recognized",
    "ordinary_type_names_are_not_stdlib_laws",
}
EXPECTED_NEGATIVE = {
    "string_type_is_a_stdlib_refinement_law",
    "nonempty_is_not_a_stdlib_refinement_law",
}


def compact(text: str) -> str:
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate source function {name}")
    return match.group(1)


source = HELPER.read_text()
body = compact(function_body(source, "is_stdlib_refinement_law"))
pattern_arms = (
    "|".join(f'"{name}"' for name in LAW_NAMES[index:index + 8]) + "->true"
    for index in range(0, len(LAW_NAMES), 8)
)
pattern = "whenname:" + "".join(pattern_arms) + "_->false"
contract = f"ensureresult==({pattern})"
if contract not in body or body.count(pattern) != 2 or f"return{pattern}" not in body:
    raise SystemExit("production refinement-law contract and return must match the exact closed law set")

consumer = compact(CONSUMER.read_text())
if 'include"./stdlib_refinement_law_name.elisa"' not in consumer:
    raise SystemExit("refinement semantic pass no longer imports the proved name classifier")
if "returnStdlibRefinementLawName::is_stdlib_refinement_law(name)" not in compact(function_body(CONSUMER.read_text(), "is_stdlib_refinement_law")):
    raise SystemExit("refinement semantic pass no longer delegates to the proved classifier")
if "or is_stdlib_refinement_law(name)" not in CONSUMER.read_text():
    raise SystemExit("declared-law and alias lookup no longer consumes the proved classifier")

proof = compact(POSITIVE.read_text())
if contract not in proof:
    raise SystemExit("positive proof no longer states the exact source refinement-law set")
for name in LAW_NAMES:
    if f'StdlibRefinementLawName::is_stdlib_refinement_law("{name}")' not in proof:
        raise SystemExit(f"positive proof no longer checks source refinement law {name!r}")
for path, expected in ((POSITIVE, EXPECTED_POSITIVE), (NEGATIVE, EXPECTED_NEGATIVE)):
    declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if declarations != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("refinement-law name proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_include_closure([POSITIVE, NEGATIVE]), HELPER, CONSUMER,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
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
assert positive == run(POSITIVE)[1], "refinement-law proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert EXPECTED_POSITIVE <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == EXPECTED_NEGATIVE
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed set of 23 builtin and standard-library refinement law names",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(EXPECTED_NEGATIVE),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
