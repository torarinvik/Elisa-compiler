"""Normalize Elisa return-if blocks for proof checks written against guard lines."""
from __future__ import annotations

import re


_RETURN_BLOCK = re.compile(r"^([ \t]*)(return(?:[ \t]+.+?)?)[ \t]+if:[ \t]*(?:#.*)?$")
_DECLARATION = re.compile(r"^[A-Za-z_]\w*(?:\[[^\]]+\])?\s*:\s*[A-Za-z_]\w*(?:\s|\[|&|\.|$)")
_CONTROL = re.compile(r"^(?:if|while|for|can|assert|ensure|invariant|decreases|return|break|continue)\b")


def _starts_statement(line: str) -> bool:
    return bool(
        _CONTROL.match(line)
        or _DECLARATION.match(line)
        or re.match(r"^[A-Za-z_]\w*(?:\[[^\]]+\])?\s*<-", line)
    )


def return_if_block_count(source: str) -> int:
    return sum(_RETURN_BLOCK.match(line) is not None for line in source.splitlines())


def logical_source_line_count(source: str) -> int:
    """Count a guard header with its conditions as the former guard lines."""
    return len(source.splitlines()) - return_if_block_count(source)


def expand_return_if_blocks(source: str) -> str:
    """Expand each return-if block into equivalent one-condition guard lines."""
    lines = source.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        header = _RETURN_BLOCK.match(lines[index])
        if header is None:
            result.append(lines[index])
            index += 1
            continue

        indent, statement = header.groups()
        conditions: list[str] = []
        next_index = index + 1
        while next_index < len(lines):
            candidate = lines[next_index]
            if not candidate.strip() or candidate.lstrip().startswith("#"):
                next_index += 1
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
            if candidate_indent <= len(indent):
                break
            expression = candidate.strip()
            if _starts_statement(expression):
                break
            conditions.append(expression)
            next_index += 1

        if not conditions:
            result.append(lines[index])
            index += 1
            continue
        value = statement.removeprefix("return").strip()
        # The compact historical spelling used by the proof checks had two forms:
        # value-first guards for simple values and return-first guards for aggregate
        # expressions. Keep those textual contracts stable while reading block syntax.
        legacy = f"return {value} if" if value.startswith(("(", "[", "{")) else f"{value} return if"
        result.extend(f"{indent}{legacy} {condition}" for condition in conditions)
        index = next_index
    return "\n".join(result)
