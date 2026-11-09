"""Inspect source and proof declarations for backend index guards."""
from __future__ import annotations

from pathlib import Path
import re


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())

def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\]\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\n]*\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]

def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))

def require_ordered(source: str, steps: tuple[str, ...], label: str) -> None:
    positions: list[int] = []
    cursor = 0
    for step in steps:
        position = source.find(step, cursor)
        positions.append(position)
        if position >= 0:
            cursor = position + len(step)
    if any(position < 0 for position in positions):
        raise SystemExit(f"{label} changed its proved operation order: {positions}")
