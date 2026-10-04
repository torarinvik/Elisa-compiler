#!/usr/bin/env python3
"""Record and verify the exact source inputs behind a local Stage1 product."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


SCHEMA = "elisa-stage1-provenance-v1"
SOURCE_DIRS = ("src", "elisacore_std")
BUILD_RECIPES = (
    "scripts/elisac_stage1.sh",
    "scripts/elisac_stage1_seed.sh",
    "scripts/build_runtime_object.sh",
    "scripts/write_profiler_hook_fallbacks.sh",
)


def digest_files(root, paths):
    digest = hashlib.sha256()
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
        elif path.is_file():
            files.append(path)
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_revision(root):
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    # Informational only: a tree shipped without .git (remote gates) still has a provenance.
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def snapshot(root, binary):
    root = Path(root).resolve()
    binary = Path(binary).resolve()
    missing = [name for name in SOURCE_DIRS + BUILD_RECIPES if not (root / name).exists()]
    if missing:
        raise RuntimeError(f"Stage1 provenance inputs are missing: {', '.join(missing)}")
    return {
        "schema": SCHEMA,
        "source_revision": source_revision(root),
        "source_tree_sha256": digest_files(root, [root / name for name in SOURCE_DIRS]),
        "build_recipe_sha256": digest_files(root, [root / name for name in BUILD_RECIPES]),
        "product_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }


def manifest_path(binary):
    return Path(f"{Path(binary)}.provenance.json")


def record(root, binary):
    binary = Path(binary).resolve()
    manifest = manifest_path(binary)
    data = snapshot(root, binary)
    temporary = manifest.with_name(f"{manifest.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, manifest)
    print(f"stage1 provenance: recorded {data['source_revision']} for {binary}")


def check(root, binary):
    binary = Path(binary).resolve()
    manifest = manifest_path(binary)
    try:
        recorded = json.loads(manifest.read_text())
        current = snapshot(root, binary)
    except (OSError, json.JSONDecodeError, RuntimeError) as error:
        print(f"stage1 provenance cannot be verified: {error}", file=sys.stderr)
        return 2
    # Freshness is decided by CONTENT. The git revision is recorded for humans but not compared:
    # committing after a seed changes HEAD without changing a single input byte.
    changed = [key for key, value in current.items()
               if key != "source_revision" and recorded.get(key) != value]
    if changed:
        print("stage1 product is stale: provenance mismatch in " + ", ".join(changed), file=sys.stderr)
        return 2
    # Silent on success: assert_stage1_fresh.sh runs before EVERY wrapper compile, so a line
    # here lands in the compiler's own output (stdout of `-emit ast`/`fmt`, the first stderr
    # line a parity gate compares). ELISA_PROVENANCE_VERBOSE=1 prints it.
    if os.environ.get("ELISA_PROVENANCE_VERBOSE") == "1":
        print(f"stage1 provenance: current ({current['source_revision']})", file=sys.stderr)
    return 0


def main(argv):
    if len(argv) != 4 or argv[1] not in ("record", "check"):
        print("usage: stage1_provenance.py (record|check) ROOT BIN", file=sys.stderr)
        return 2
    try:
        if argv[1] == "record":
            record(argv[2], argv[3])
            return 0
        return check(argv[2], argv[3])
    except (OSError, RuntimeError) as error:
        print(f"stage1 provenance failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
