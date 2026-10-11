#!/usr/bin/env python3
"""Generate source-only warm-cache key-lookup workloads; no compiler is invoked."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
parser.add_argument("--helpers", type=int, nargs="+", default=[1, 8, 256, 1024, 4096])
parser.add_argument("--low-query", action="store_true", help="include one supported helper among generic, uncacheable declarations")
parser.add_argument("--dense-calls", action="store_true", help="include a chain with one direct call per helper after the leaf")
args = parser.parse_args()
if any(count < 1 for count in args.helpers):
    parser.error("helper counts must be positive")
records = []
for count in args.helpers:
    directory = args.output / ("n%05d" % count)
    directory.mkdir(parents=True, exist_ok=True)
    original = "".join(f"def cache_fn_{i:06d}() -> i64:\n    return {i}\n" for i in range(count))
    original += "def main() -> i64:\n    return cache_fn_000000()\n"
    edited = original.replace("    return 0\n", "    return 1\n", 1)
    hashes = {}
    for name, source in [("program.elisa", original), ("program.body-edit.elisa", edited)]:
        data = source.encode()
        (directory / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    records.append({"directory": directory.name, "helpers": count, "functions": count + 1, "sha256": hashes})
if args.dense_calls:
    for count in args.helpers:
        directory = args.output / ("dense-call-n%05d" % count)
        directory.mkdir(parents=True, exist_ok=True)
        original = "def cache_fn_000000() -> i64:\n    return 0\n"
        original += "".join(f"def cache_fn_{i:06d}() -> i64:\n    return cache_fn_{i - 1:06d}()\n" for i in range(1, count))
        original += f"def main() -> i64:\n    return cache_fn_{count - 1:06d}()\n"
        edited = original.replace("    return 0\n", "    return 1\n", 1)
        hashes = {}
        for name, source in [("program.elisa", original), ("program.body-edit.elisa", edited)]:
            data = source.encode()
            (directory / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        records.append({"directory": directory.name, "helpers": count, "functions": count + 1, "direct_calls": count, "sha256": hashes})
if args.low_query:
    for count in args.helpers:
        directory = args.output / ("low-query-n%05d" % count)
        directory.mkdir(parents=True, exist_ok=True)
        original = "def cache_fn_000000() -> i64:\n    return 0\n"
        original += "".join(f"def rejected_fn_{i:06d}[T](value: T) -> T:\n    return value\n" for i in range(1, count))
        original += "def main() -> i64:\n    return cache_fn_000000()\n"
        edited = original.replace("    return 0\n", "    return 1\n", 1)
        hashes = {}
        for name, source in [("program.elisa", original), ("program.body-edit.elisa", edited)]:
            data = source.encode()
            (directory / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        records.append({"directory": directory.name, "helpers": count, "functions": count + 1, "supported_helpers": 1, "sha256": hashes})
args.output.mkdir(parents=True, exist_ok=True)
(args.output / "manifest.json").write_text(json.dumps({"schema": 1, "purpose": "warm compatible-snapshot key lookup; prime original then edit one body at the same absolute path", "workloads": records}, indent=2) + "\n")
