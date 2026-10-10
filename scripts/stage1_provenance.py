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
    "scripts/stage1_object_cache.py",
    "scripts/elisac_stage1_seed.sh",
    "scripts/assert_stage0_fresh.sh",
    "scripts/process_rss.sh",
    "scripts/build_runtime_object.sh",
    "scripts/write_profiler_hook_fallbacks.sh",
    "scripts/stage1_provenance.py",
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
    if result.returncode == 0:
        return result.stdout.strip()
    snapshot = root / "SNAPSHOT"
    if snapshot.is_file():
        for line in snapshot.read_text().splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() == "source_revision" and value.strip():
                return value.strip()
    raise RuntimeError(f"cannot read Stage1 source revision from {root}")


def input_fingerprint(root):
    root = Path(root).resolve()
    missing = [name for name in SOURCE_DIRS + BUILD_RECIPES if not (root / name).exists()]
    if missing:
        raise RuntimeError(f"Stage1 provenance inputs are missing: {', '.join(missing)}")
    return {
        "source_tree_sha256": digest_files(root, [root / name for name in SOURCE_DIRS]),
        "build_recipe_sha256": digest_files(root, [root / name for name in BUILD_RECIPES]),
    }


def snapshot(root, binary):
    root = Path(root).resolve()
    binary = Path(binary).resolve()
    return {
        "schema": SCHEMA,
        "source_revision": source_revision(root),
        **input_fingerprint(root),
        "product_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }


def manifest_path(binary):
    return Path(f"{Path(binary)}.provenance.json")


def record(root, binary, expected_inputs=None):
    binary = Path(binary).resolve()
    manifest = manifest_path(binary)
    data = snapshot(root, binary)
    if expected_inputs is not None:
        if not isinstance(expected_inputs, dict):
            raise RuntimeError("expected Stage1 input fingerprint must be a JSON object")
        changed = [key for key in ("source_tree_sha256", "build_recipe_sha256")
                   if expected_inputs.get(key) != data[key]]
        if changed:
            raise RuntimeError(
                "Stage1 inputs changed during seed; refusing to record provenance for "
                + ", ".join(changed)
            )
    temporary = manifest.with_name(f"{manifest.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, manifest)
    print(f"stage1 provenance: recorded {data['source_revision']} for {binary}")


def check_inputs(root, expected_inputs):
    if not isinstance(expected_inputs, dict):
        raise RuntimeError("expected Stage1 input fingerprint must be a JSON object")
    current = input_fingerprint(root)
    changed = [key for key, value in current.items() if expected_inputs.get(key) != value]
    if changed:
        print(
            "Stage1 inputs changed during seed: " + ", ".join(changed),
            file=sys.stderr,
        )
        return 2
    return 0


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
    if len(argv) < 2:
        print("usage: stage1_provenance.py (record|check|inputs|check-inputs) ...", file=sys.stderr)
        return 2
    try:
        if argv[1] == "record":
            if len(argv) not in (4, 5):
                raise RuntimeError("usage: stage1_provenance.py record ROOT BIN [EXPECTED_INPUTS_JSON]")
            expected_inputs = json.loads(argv[4]) if len(argv) == 5 else None
            record(argv[2], argv[3], expected_inputs)
            return 0
        if argv[1] == "check":
            if len(argv) != 4:
                raise RuntimeError("usage: stage1_provenance.py check ROOT BIN")
            return check(argv[2], argv[3])
        if argv[1] == "inputs":
            if len(argv) != 3:
                raise RuntimeError("usage: stage1_provenance.py inputs ROOT")
            print(json.dumps(input_fingerprint(argv[2]), separators=(",", ":"), sort_keys=True))
            return 0
        if argv[1] == "check-inputs":
            if len(argv) != 4:
                raise RuntimeError("usage: stage1_provenance.py check-inputs ROOT EXPECTED_INPUTS_JSON")
            return check_inputs(argv[2], json.loads(argv[3]))
        print("usage: stage1_provenance.py (record|check|inputs|check-inputs) ...", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as error:
        print(f"stage1 provenance failed: {error}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as error:
        print(f"stage1 provenance failed: invalid input fingerprint: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
