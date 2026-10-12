"""Check the backend target-machine optimization-level clamp proof."""
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
SOURCE = ROOT / "src/backend/codegen_target_machine.elisa"
POSITIVE = HERE / "codegen_level_clamp.elisa"
NEGATIVE = HERE / "codegen_level_clamp_rejected.elisa"

source = SOURCE.read_text()
match = re.search(
    r"(?ms)^[ \t]*def configure_module_target_for_level\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
    source,
)
if match is None:
    raise SystemExit("could not locate target-machine level selection")
body = "".join(match.group(1).split())
selection = "machine_level:i32=requested_level.i32()ifrequested_level>=0andrequested_level<=3else0"
if selection not in body:
    raise SystemExit("target-machine level conversion no longer clamps before passing an LLVM enum")

expected_positive = {
    "every_requested_level_clamps_to_enum_domain",
    "supported_requested_level_is_preserved",
    "unsupported_requested_level_becomes_zero",
}
expected_negative = {
    "clamped_level_can_escape_enum_domain",
    "unsupported_level_is_not_reset",
}
declarations = lambda path: set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
if declarations(POSITIVE) != expected_positive or declarations(NEGATIVE) != expected_negative:
    raise SystemExit("codegen level clamp proof inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("codegen level clamp proof requires a strict proof build")


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 6
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == expected_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 4 and negative["summary"]["proven"] == 2
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in expected_negative
}

print(json.dumps({
    "scope": "all requested LLVM optimization levels clamp to 0..3, preserving valid levels",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
}, sort_keys=True))
