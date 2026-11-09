"""Normalize and inspect Elisa source for generic slot proofs."""
from pathlib import Path
import re


def strip_elisa_line_comment(line: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return line[:index]
    return line

def normalize_code_line(code: str) -> str:
    output = []
    quote = None
    escaped = False
    pending_space = False
    for char in code.strip():
        if quote is not None:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            if pending_space and output:
                output.append(" ")
            pending_space = False
            quote = char
            output.append(char)
        elif char.isspace():
            pending_space = True
        else:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            output.append(char)
    return "".join(output)

def normalized_lines(text: str) -> tuple[tuple[int, str], ...]:
    lines = []
    for line in text.splitlines():
        uncommented = strip_elisa_line_comment(line).expandtabs(4)
        if uncommented.strip():
            indent = len(uncommented) - len(uncommented.lstrip())
            lines.append((indent, normalize_code_line(uncommented.lstrip())))
    if not lines:
        return ()
    base_indent = min(indent for indent, _ in lines)
    return tuple((indent - base_indent, code) for indent, code in lines)

def include_targets(text: str) -> list[str]:
    targets = []
    for line in text.splitlines():
        directive = strip_elisa_line_comment(line).strip()
        match = re.fullmatch(r'include\s+"([^"\n]+)"', directive)
        if match:
            targets.append(match.group(1))
    return targets

def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]

def exact_steps(source: str, name: str, steps: tuple[tuple[int, str], ...], label: str) -> None:
    lines = normalized_lines(function_section(source, name))
    cursor = 0
    for indent, code in steps:
        expected = (indent, normalize_code_line(code))
        try:
            cursor = lines.index(expected, cursor) + 1
        except ValueError:
            raise SystemExit(f"{label}: missing or reordered source line: {code}") from None

def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
