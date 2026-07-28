#!/usr/bin/env python3
"""Package stage1 object files and the Elisa runtime into a C archive."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ar", default=os.environ.get("AR") or shutil.which("ar"))
    parser.add_argument("objects", nargs="+", type=Path)
    args = parser.parse_args()
    if not args.ar:
        parser.error("ar not found; set AR")
    missing = [str(path) for path in args.objects if not path.is_file()]
    if missing:
        parser.error("object file not found: " + ", ".join(missing))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="elisa-c-archive-", dir=args.output.parent) as temp:
        temporary = Path(temp) / args.output.name
        command = [args.ar, "-rcs", str(temporary), *(str(path) for path in args.objects)]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if completed.returncode:
            raise SystemExit(completed.stderr.decode(errors="replace").strip() or "ar failed")
        os.replace(temporary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
