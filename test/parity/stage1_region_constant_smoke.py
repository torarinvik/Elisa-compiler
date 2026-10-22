#!/usr/bin/env python3
"""Check Stage1 region-only calls and integer constant match selectors."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
STAGE1 = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "bin/elisac-stage1"

if not STAGE1.is_file() or not os.access(STAGE1, os.X_OK):
    raise SystemExit(f"Stage1 product is not executable: {STAGE1}")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"30-second timeout: {command[0]}")


freshness = run(["bash", str(ROOT / "scripts/assert_stage1_fresh.sh"), str(STAGE1)])
if freshness.returncode:
    raise SystemExit(f"Stage1 product is stale or invalid:\n{freshness.stdout}{freshness.stderr}")

fixtures = ROOT / "test/fixtures"
cases = (
    ("self_parse_syntax/region_only_specialization.elisa", True, ""),
    ("self_parse_syntax/region_only_generic_name_collision.elisa", True, ""),
    ("self_parse_syntax/scalar_named_constant_match.elisa", True, ""),
    ("self_parse_syntax/ordinary_function_region_arg.neg.elisa", False, "is not generic"),
    ("self_parse_syntax/scalar_constant_local_shadow.neg.elisa", False, "integer match arm"),
)

for name, accepted, expected in cases:
    result = run([str(STAGE1), "-emit", "check", str(fixtures / name)])
    output = result.stdout + result.stderr
    valid = result.returncode == 0 if accepted else result.returncode != 0 and expected in output
    if not valid:
        outcome = "accept" if accepted else f"reject with {expected!r}"
        raise SystemExit(f"Stage1 did not {outcome} {name} (exit {result.returncode}):\n{output}")
    print(f"stage1 {name}: ok")

with tempfile.TemporaryDirectory(prefix="elisa-stage1-region-constant-") as directory:
    for name in (
        "region_only_specialization.elisa",
        "region_only_generic_name_collision.elisa",
        "scalar_named_constant_match.elisa",
    ):
        output = Path(directory) / f"{name}.ll"
        result = run([
            str(STAGE1), "-emit", "llvm", "-O0", "-o", str(output),
            str(fixtures / "self_parse_syntax" / name),
        ])
        if result.returncode or not output.is_file() or output.stat().st_size == 0:
            text = result.stdout + result.stderr
            raise SystemExit(f"Stage1 failed to emit LLVM for {name}:\n{text}")
        print(f"stage1 LLVM {name}: ok")
