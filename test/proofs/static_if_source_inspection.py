"""Inspect Elisa source structure for static-if proofs."""
from pathlib import Path
import re

ELISA_INDENT_WIDTH = 4


def source_code(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())

def compact(text: str) -> str:
    return "".join(source_code(text).split())

def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]

def direct_children(lines: list[str], parent_index: int, parent_indent: int) -> list[str]:
    children: list[str] = []
    for line in lines[parent_index + 1:]:
        content = line.lstrip(" \t")
        if not content or content.startswith("#"):
            continue
        indent = len(line) - len(content)
        if indent <= parent_indent:
            break
        if indent == parent_indent + ELISA_INDENT_WIDTH:
            children.append(content)
    return children

def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
