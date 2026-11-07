#!/usr/bin/env python3
"""Guard against exponential semantic lookup on resolvable field chains."""
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
reporter = os.environ.get("ELISA_PARSE_REPORT", str(root / "build/parse_report"))
chain = "a" + ".b" * 28
source = f"""struct Node:
    b: Node&

def f(a: Node&) -> i64:
    _ = {chain}
    return 0
"""
try:
    result = subprocess.run([reporter], input=source, text=True, capture_output=True,
                            timeout=5, check=True)
except subprocess.TimeoutExpired as error:
    raise SystemExit("field-chain semantic analysis exceeded 5 seconds") from error
if "P 0\nD 0\n" not in result.stdout:
    raise SystemExit(f"unexpected field-chain diagnostics:\n{result.stdout}\n{result.stderr}")
print("field-chain semantic analysis passed")
