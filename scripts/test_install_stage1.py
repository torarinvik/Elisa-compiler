#!/usr/bin/env python3
"""Check snapshots preserve immutable seed inputs and failed installs are atomic."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from stage1_provenance import fingerprint_artifact, seed_configuration_fingerprint, toolchain_content_view

installer = Path(__file__).resolve().with_name("install_stage1.sh")
with tempfile.TemporaryDirectory(prefix="elisa-install-control-") as directory:
    root = Path(directory) / "source"
    prefix = Path(directory) / "installed"
    for name in ["scripts", "src", "elisacore_std", "bin", "build/runtime"]:
        (root / name).mkdir(parents=True, exist_ok=True)
    for name in ("install_stage1.sh", "stage1_snapshot.py", "stage1_provenance.py"):
        shutil.copy2(installer.with_name(name), root / "scripts" / name)
    product = root / "bin/elisac-stage1"
    product.write_text("#!/bin/sh\nexit 0\n")
    product.chmod(0o755)
    bootstrap = Path(directory) / "bootstrap"
    bootstrap.write_bytes(b"bootstrap compiler fixture")
    bootstrap_runtime = Path(directory) / "bootstrap-runtime.o"
    bootstrap_runtime.write_bytes(b"bootstrap runtime fixture")
    seed = {
        "bootstrap_compiler": fingerprint_artifact(bootstrap, exact=True),
        "bootstrap_kind": "stage1",
        "bootstrap_runtime_object": fingerprint_artifact(bootstrap_runtime, exact=True),
        "bootstrap_runtime_expected_sha256": fingerprint_artifact(bootstrap_runtime, exact=True)["sha256"],
    }
    (root / "bin/elisac-stage1.provenance.json").write_text(json.dumps({"seed_configuration": seed, "product_sha256": fingerprint_artifact(product, exact=True)["sha256"]}))
    runtime = root / "build/runtime/elisacore_runtime.o"
    runtime.write_bytes(b"runtime fixture")
    stamp = Path(str(runtime) + ".inputs.sha256")
    stamp.write_text("runtime input and object digest fixture\n")
    env = {**os.environ, "ELISAC_PREFIX": str(prefix)}
    command = ["bash", str(root / "scripts/install_stage1.sh")]
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert (prefix / "elisacore_runtime.o").read_bytes() == runtime.read_bytes()
    assert (prefix / "elisacore_runtime.o.inputs.sha256").read_bytes() == stamp.read_bytes()
    assert (prefix / "stage1/build/runtime/elisacore_runtime.o.inputs.sha256").read_bytes() == stamp.read_bytes()
    installed = json.loads((prefix / "stage1/bin/elisac-stage1.provenance.json").read_text())["seed_configuration"]
    assert Path(installed["bootstrap_compiler"]["path"]).read_bytes() == bootstrap.read_bytes()
    assert Path(installed["bootstrap_runtime_object"]["path"]).read_bytes() == bootstrap_runtime.read_bytes()
    assert not list(prefix.glob(".stage1.incoming.*"))
    previous = {str(path.relative_to(prefix)): path.read_bytes() for path in prefix.rglob('*') if path.is_file()}
    stamp.unlink()
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 2 and "no runtime freshness stamp" in result.stderr, result
    assert {str(p.relative_to(prefix)): p.read_bytes() for p in prefix.rglob('*') if p.is_file()} == previous
    stamp.write_text("runtime input and object digest fixture\n")
    original_product = product.read_bytes()
    product.write_bytes(b"tampered source product")
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 2 and "product binary does not match" in result.stderr, result
    assert {str(p.relative_to(prefix)): p.read_bytes() for p in prefix.rglob('*') if p.is_file()} == previous
    assert not list(prefix.glob(".stage1.incoming.*"))
    product.write_bytes(original_product)
    # Replacing/removing development inputs cannot invalidate the frozen installed receipt.
    bootstrap.write_bytes(b"new development compiler")
    bootstrap_runtime.unlink()
    producer_variables = ("ELISA_STAGE1_SEED_BOOTSTRAP_BIN", "ELISA_STAGE1_SEED_STAGE0_BIN",
                          "BOOTSTRAP_BIN", "STAGE0_BIN", "ELISACORE_BIN")
    saved = {key: os.environ.pop(key) for key in producer_variables if key in os.environ}
    try:
        current = seed_configuration_fingerprint(installed, exact=True)
    finally:
        os.environ.update(saved)
    assert toolchain_content_view(current) == toolchain_content_view(installed)
    # Installing from an outdated receipt must fail before touching the previous snapshot.
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 2 and "bootstrap_compiler changed" in result.stderr, result
    assert {str(p.relative_to(prefix)): p.read_bytes() for p in prefix.rglob('*') if p.is_file()} == previous
    assert not list(prefix.glob(".stage1.incoming.*"))
    frozen = Path(installed["bootstrap_compiler"]["path"])
    frozen.write_bytes(b"tampered installed compiler")
    saved = {key: os.environ.pop(key) for key in producer_variables if key in os.environ}
    try:
        assert toolchain_content_view(seed_configuration_fingerprint(installed, exact=True)) != toolchain_content_view(installed)
    finally:
        os.environ.update(saved)
with tempfile.TemporaryDirectory(prefix="elisa bootstrap discovery ") as directory:
    root = Path(directory)
    source = root / "Elisa Projects" / "Elisa-compiler"
    source.mkdir(parents=True)
    bootstrap = root / "Go projects" / "Elisa-core" / "compiler" / "bin" / "elisac"
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_text("not a compiler\n")
    bootstrap.chmod(0o755)
    snapshot = root / "installed snapshot"
    snapshot.mkdir()
    shutil.copytree(installer.parent, snapshot / "scripts", symlinks=True)
    (snapshot / "SNAPSHOT").write_text(f"from:     {source}\n")
    env = os.environ.copy()
    for key in ("ELISACORE_BIN", "ELISA_STAGE1_SEED_BOOTSTRAP_KIND", "ELISA_STAGE1_BIN"):
        env.pop(key, None)
    result = subprocess.run(["bash", str(snapshot / "scripts/elisac_stage1.sh"), "--seed"],
                            env=env, capture_output=True, text=True)
    # The fixture is deliberately not a compiler; bootstrap identification must
    # fail on the discovered path before starting an expensive seed build.
    assert result.returncode == 2 and str(bootstrap) in result.stderr, result
print("Stage1 installation control passed: immutable seed inputs, tamper detection, atomic failure, runtime stamp, snapshot bootstrap discovery")
