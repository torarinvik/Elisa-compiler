#!/usr/bin/env python3
"""Expand local includes for stdin-based compiler probes and retain a line map.

This is diagnostic tooling, not the production include loader or a cache key.
Usage: expand_source_probe.py INPUT OUTPUT [LINE_MAP_JSON] [--preserve-std]

Use --preserve-std when compiling the expanded probe itself, so the bootstrap
loader can verify the original standard-runtime include identity. Omit it when
preparing a fully expanded stdin unit for a native probe.
"""
import argparse
import json
from pathlib import Path
import re

seen = set()
chunks = []
line_map = []
next_line = 1
preserve_std = False


def append(text, source, source_line):
    global next_line
    count = text.count("\n")
    if not text.endswith("\n"):
        text += "\n"
        count += 1
    chunks.append(text)
    line_map.append({"start": next_line, "count": count, "source": str(source), "line": source_line})
    next_line += count


def expand(path):
    path = path.resolve(strict=True)
    if path in seen:
        return
    seen.add(path)
    if preserve_std and "elisacore_std" in path.parts:
        append(f'include "{path}"\n', path, 1)
        return
    pending = []
    first_line = 1
    for number, line in enumerate(path.read_text().splitlines(keepends=True), 1):
        include = re.match(r'^include\s+"([^"\n]+)"\s*(?:#.*)?$', line.rstrip("\n"))
        if include:
            if pending:
                append("".join(pending), path, first_line)
                pending = []
            expand(path.parent / include[1])
            first_line = number + 1
        else:
            pending.append(line)
    if pending:
        append("".join(pending), path, first_line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("line_map", type=Path, nargs="?")
    parser.add_argument("--preserve-std", action="store_true")
    args = parser.parse_args()
    preserve_std = args.preserve_std
    expand(args.input)
    args.output.write_text("".join(chunks))
    if args.line_map:
        args.line_map.write_text(json.dumps(line_map))
