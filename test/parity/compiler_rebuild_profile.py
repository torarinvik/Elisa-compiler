"""Extract a Go compiler package name without exposing its other arguments."""

from __future__ import annotations

from pathlib import Path
import re
import shlex

_PACKAGE = re.compile(r"[A-Za-z0-9_./-]+\Z")


def go_compiler_package(command: str) -> str | None:
    match = re.search(r"(?:^|\s)-p\s+([A-Za-z0-9_./-]+)(?:\s|$)", command)
    if match:
        return match.group(1)
    # Go normally uses a response file when the command line is long. `ps`
    # reports it as the final @ argument and does not quote embedded spaces.
    marker = command.find(" @")
    if marker < 0:
        return None
    path = Path(command[marker + 2:].strip())
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            return None
        args = shlex.split(path.read_text(encoding="utf-8"))
        index = args.index("-p")
        name = args[index + 1]
    except (OSError, UnicodeError, ValueError, IndexError):
        return None
    return name if _PACKAGE.fullmatch(name) else None
