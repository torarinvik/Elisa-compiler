#!/usr/bin/env python3
"""Check snapshot installation preserves runtime bootstrap provenance."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

installer = Path(__file__).resolve().with_name("install_stage1.sh")
with tempfile.TemporaryDirectory(prefix="elisa-install-control-") as directory:
    root = Path(directory) / "source"
    prefix = Path(directory) / "installed"
    for name in ["scripts", "src", "elisacore_std", "bin", "build/runtime"]:
        (root / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(installer, root / "scripts/install_stage1.sh")
    product = root / "bin/elisac-stage1"
    product.write_text("#!/bin/sh\nexit 0\n")
    product.chmod(0o755)
    (root / "bin/elisac-stage1.provenance.json").write_text("{}\n")
    runtime = root / "build/runtime/elisacore_runtime.o"
    runtime.write_bytes(b"runtime fixture")
    stamp = Path(str(runtime) + ".inputs.sha256")
    stamp.write_text("runtime input and object digest fixture\n")
    env = {**os.environ, "ELISAC_PREFIX": str(prefix)}
    subprocess.run(["bash", str(root / "scripts/install_stage1.sh")], env=env, check=True, capture_output=True)
    assert (prefix / "elisacore_runtime.o").read_bytes() == runtime.read_bytes()
    assert (prefix / "elisacore_runtime.o.inputs.sha256").read_bytes() == stamp.read_bytes()
    assert (prefix / "stage1/build/runtime/elisacore_runtime.o.inputs.sha256").read_bytes() == stamp.read_bytes()
    previous = {str(path.relative_to(prefix)): path.read_bytes() for path in prefix.rglob('*') if path.is_file()}
    stamp.unlink()
    result = subprocess.run(["bash", str(root / "scripts/install_stage1.sh")], env=env, capture_output=True, text=True)
    assert result.returncode == 2 and "no runtime freshness stamp" in result.stderr, result
    current = {str(path.relative_to(prefix)): path.read_bytes() for path in prefix.rglob('*') if path.is_file()}
    assert current == previous, "failed installation modified the previous snapshot"
print("Stage1 installation control passed: bootstrap stamp preserved; missing stamp leaves installed snapshot intact")
