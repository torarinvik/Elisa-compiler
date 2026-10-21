#!/usr/bin/env python3
"""Check region/constant rules through the complete native semantic probe."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CHECKER = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ELISA_SEMANTIC_CHECKER_BIN")
if not CHECKER:
    raise SystemExit("Pass the check_native executable or set ELISA_SEMANTIC_CHECKER_BIN")

for name, rejection in (
    ("region_only_specialization", None),
    ("region_only_generic_name_collision", None),
    ("scalar_named_constant_match", None),
    ("ordinary_function_region_arg.neg", 'function "ordinary" is not generic'),
    ("scalar_constant_local_shadow.neg", "integer match arm"),
):
    source = ROOT / "test/fixtures/self_parse_syntax" / (name + ".elisa")
    try:
        result = subprocess.run([CHECKER], input=source.read_bytes(), capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"30-second timeout: {name}")
    output = (result.stdout + result.stderr).decode(errors="replace")
    valid = "parse-errors=0\n" in output
    if rejection is None:
        valid = valid and result.returncode == 0 and "diagnostics=0\n" in output
    else:
        valid = valid and result.returncode == 1 and rejection in output and "diagnostics=1\n" in output
    if not valid:
        raise SystemExit(f"semantic fixture failed: {name} (exit {result.returncode})\n{output}")
    print(f"semantic {name}: ok")
