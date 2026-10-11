"""Validate the exact strict Elisa-proof product used by compiler proof gates."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Optional


MANIFEST_SCHEMA = "elisa-proof-build-manifest-v1"
STAGE1_SCHEMA = "elisa-stage1-provenance-v1"


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for directory, subdirectories, files in os.walk(root):
        subdirectories.sort()
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *arguments], check=True,
                            capture_output=True, text=True)
    return result.stdout.strip()


def _check_file(record: dict, label: str, expected_path: Optional[Path] = None) -> str:
    if not isinstance(record, dict):
        raise ValueError(f"proof manifest has no {label} identity")
    path_text = record.get("path")
    expected_digest = record.get("sha256")
    expected_bytes = record.get("bytes")
    if not isinstance(path_text, str) or not isinstance(expected_digest, str):
        raise ValueError(f"proof manifest has incomplete {label} identity")
    path = Path(path_text).resolve(strict=True)
    if expected_path is not None and path != expected_path.resolve(strict=True):
        raise ValueError(f"proof manifest {label} path does not match selected product")
    data = path.read_bytes()
    actual_digest = hashlib.sha256(data).hexdigest()
    if actual_digest != expected_digest or len(data) != expected_bytes:
        raise ValueError(f"proof manifest {label} digest or size is stale")
    return actual_digest


def require_current_product(binary: Path, prover_root: Path) -> dict:
    """Reject stale, permissive, or provenance-mismatched proof executables."""
    binary = binary.resolve(strict=True)
    prover_root = prover_root.resolve(strict=True)
    manifest_path = binary.with_name(binary.name + ".manifest.json")
    checksum_path = manifest_path.with_name(manifest_path.name + ".sha256")
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise ValueError(f"missing proof manifest or checksum beside {binary}")
    manifest_bytes = manifest_path.read_bytes()
    expected_manifest_digest = checksum_path.read_text(encoding="ascii").strip()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_digest:
        raise ValueError("proof build manifest checksum does not match its sidecar")
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unknown proof build manifest schema")
    if manifest.get("compile_mode") != "strict":
        raise ValueError("compiler proof gates require a strict proof executable")
    compiler = manifest.get("compiler")
    if not isinstance(compiler, dict):
        raise ValueError("proof manifest has no compiler build identity")

    _check_file(manifest.get("binary"), "proof executable", binary)
    _check_file(compiler.get("executable"), "compiler executable")
    compiler_digest = _check_file(compiler.get("product"), "Stage1 compiler")
    _check_file(manifest.get("runtime"), "compiler runtime")
    _check_file(manifest.get("profile_hooks"), "profile hooks")

    proof = manifest.get("proof")
    if not isinstance(proof, dict):
        raise ValueError("proof manifest has no proof-source identity")
    source_root = prover_root / "src"
    current_head = _git(prover_root, "rev-parse", "HEAD")
    current_dirty = bool(_git(prover_root, "status", "--porcelain", "--", "src"))
    if proof.get("head") != current_head or proof.get("source_dirty") != current_dirty:
        raise ValueError("proof executable was built from a different proof-source revision or dirty state")
    if proof.get("source_tree_sha256") != _tree_digest(source_root):
        raise ValueError("proof executable was built from a different proof-source tree")

    if compiler.get("stage") != "stage1":
        raise ValueError("compiler proof gates require a Stage1-built proof executable")
    revision_pin = (prover_root / "ELISA_COMPILER_REV").read_text(encoding="ascii").strip()
    revision = compiler.get("source_revision")
    if (not revision_pin or revision != revision_pin or
            compiler.get("stage1_revision") != revision_pin or
            compiler.get("source_dirty") is not False):
        raise ValueError("proof executable compiler provenance does not match ELISA_COMPILER_REV")

    stage1_path = Path(compiler["product"]["path"]).resolve(strict=True)
    provenance_path = Path(str(stage1_path) + ".provenance.json")
    if not provenance_path.is_file():
        raise ValueError("Stage1 compiler provenance sidecar is missing")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if (provenance.get("schema") != STAGE1_SCHEMA or
            provenance.get("source_revision") != revision_pin or
            provenance.get("product_sha256") != compiler_digest or
            provenance.get("source_tree_sha256") != compiler.get("source_tree_sha256") or
            provenance.get("build_recipe_sha256") != compiler.get("build_recipe_sha256")):
        raise ValueError("Stage1 compiler provenance does not match the proof build manifest")
    return manifest
