"""Read parity smoke checks together with their explicitly sourced case files."""
from __future__ import annotations

import ast
from pathlib import Path
import re


SHELL_CASE = re.compile(r'^\s*source "\$(?:ROOT|REPO_ROOT)/test/parity/([a-zA-Z0-9_]+\.sh)"\s*$', re.MULTILINE)
UNSAFE_DRIVER = 'python3 "$REPO_ROOT/test/parity/unsafe_grant_scope_cases.py"'


def parity_smoke_inputs(path: Path) -> list[Path]:
    """Return the exact source files used by supported, local smoke fragments."""
    result = []
    active = set()

    def visit(current: Path) -> None:
        current = current.resolve()
        if current in active:
            raise ValueError(f"cyclic parity smoke include: {current}")
        if current in result:
            return
        active.add(current)
        result.append(current)
        text = current.read_text()
        for match in SHELL_CASE.finditer(text):
            visit(current.parent / match.group(1))
        if UNSAFE_DRIVER in text:
            driver = current.parent / "unsafe_grant_scope_cases.py"
            visit(driver)
            tree = ast.parse(driver.read_text())
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("unsafe_grant_"):
                    visit(driver.parent / (node.module + ".py"))
        active.remove(current)

    visit(path)
    return result


def read_parity_smoke_source(path: Path) -> str:
    """Read a smoke and its case sources for source-bound fixture checks."""
    return "\n".join(source.read_text() for source in parity_smoke_inputs(path))
