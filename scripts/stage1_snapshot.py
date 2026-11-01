#!/usr/bin/env python3
"""Freeze a Stage1 snapshot's recorded seed artifacts before publication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from stage1_provenance import fingerprint_artifact, valid_sha256


def freeze_seed_inputs(staging: Path, destination: Path) -> None:
    """Copy the exact recorded build inputs and rebase their verified receipts."""
    manifest = staging / "bin/elisac-stage1.provenance.json"
    recorded = json.loads(manifest.read_text())
    product_digest = recorded.get("product_sha256")
    if not valid_sha256(product_digest):
        raise RuntimeError("product provenance is missing its binary identity")
    if fingerprint_artifact(staging / "bin/elisac-stage1", exact=True)["sha256"] != product_digest:
        raise RuntimeError("product binary does not match its recorded digest")
    configuration = recorded.get("seed_configuration")
    if not isinstance(configuration, dict):
        raise RuntimeError("product provenance is missing its seed configuration")
    artifacts = (("bootstrap_compiler", "compiler"),
                 ("bootstrap_runtime_object", "runtime.o"))
    for field, filename in artifacts:
        artifact = configuration.get(field)
        if artifact is None and field == "bootstrap_runtime_object":
            continue
        if (not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str)
                or not valid_sha256(artifact.get("sha256"))):
            raise RuntimeError(f"product provenance has an invalid {field} identity")
        relative = Path("seed-inputs") / filename
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact["path"], target)
        copied = fingerprint_artifact(target, exact=True, description=field)
        if copied["sha256"] != artifact["sha256"]:
            raise RuntimeError(f"recorded {field} changed; rebuild Stage1 before installing")
        if (field == "bootstrap_runtime_object"
                and copied["sha256"] != configuration.get("bootstrap_runtime_expected_sha256")):
            raise RuntimeError("bootstrap runtime does not match its pinned digest")
        # The directory rename preserves the copied file's identity. The receipt names
        # its published location, never a mutable producer checkout or staging path.
        configuration[field] = {**copied, "path": str(destination / relative)}
    manifest.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staging", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        freeze_seed_inputs(args.staging.resolve(), args.destination.parent.resolve() / args.destination.name)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"cannot freeze Stage1 snapshot seed inputs: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
