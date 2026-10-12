"""Keep proof admission provenance checks byte-for-byte aligned with Stage1."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STAGE1_PROVENANCE = ROOT / "scripts/stage1_provenance.py"
sys.path.insert(0, str(HERE))
import proof_product_gate as gate  # noqa: E402


spec = importlib.util.spec_from_file_location("stage1_provenance_for_proof_gate", STAGE1_PROVENANCE)
if spec is None or spec.loader is None:
    raise SystemExit("could not load the authoritative Stage1 provenance implementation")
stage1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage1)

if gate.STAGE1_SCHEMA != stage1.SCHEMA:
    raise SystemExit("proof gate Stage1 provenance schema drifted from its producer")
if gate.STAGE1_SOURCE_DIRS != stage1.SOURCE_DIRS:
    raise SystemExit("proof gate compiler-source inventory drifted from its producer")
if gate.STAGE1_BUILD_RECIPES != stage1.BUILD_RECIPES:
    raise SystemExit("proof gate Stage1 build-recipe inventory drifted from its producer")

for paths in (gate.STAGE1_SOURCE_DIRS, gate.STAGE1_BUILD_RECIPES):
    produced_digest = stage1.digest_files(ROOT, tuple(ROOT / path for path in paths))
    admitted_digest = gate._stage1_input_digest(ROOT, paths)
    if admitted_digest != produced_digest:
        raise SystemExit(f"proof gate Stage1 fingerprint differs from producer for {paths!r}")

print("proof-product gate schema, inputs, and fingerprints match the Stage1 producer")
