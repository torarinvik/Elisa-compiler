#!/usr/bin/env python3
"""Reject omitted or miscopied fields in parallel Diagnostic ownership transfers."""
from pathlib import Path
import re


def diagnostic_literal(section: str) -> str:
    """Return a Diagnostic initializer body, respecting nested effect-set braces."""
    marker = section.find("Diagnostic{")
    assert marker >= 0, "missing Diagnostic initializer"
    opening = marker + len("Diagnostic")
    depth = 0
    in_string = False
    escaped = False
    in_comment = False
    for index in range(opening, len(section)):
        char = section[index]
        if in_comment:
            if char == "\n":
                in_comment = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == "#":
            in_comment = True
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return section[opening + 1:index]
    raise AssertionError("unterminated Diagnostic initializer")


def normalized_expression(expression: str) -> str:
    """Ignore harmless grouping and explicit effect rows around an initializer call."""
    value = expression.rstrip(",").strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    value = re.sub(r"\s+can Global\{Read,Write\}$", "", value)
    return value


def diagnostic_payload_base_type(type_expression: str) -> str:
    """Ignore a field's region annotation when classifying its payload ownership."""
    value = re.sub(r"^mutable\s+", "", type_expression.strip())
    return re.sub(r"\s+@[A-Za-z_]\w*$", "", value)


def diagnostic_payload_region(type_expression: str) -> str:
    match = re.search(r"\s+(@[A-Za-z_]\w*)$", type_expression.strip())
    return match.group(1) if match else ""


def function_section(source: str, name: str) -> str:
    """Extract one source function without relying on an adjacent comment heading."""
    lines = source.splitlines()
    start = next((index for index, line in enumerate(lines)
                  if re.match(r"^[ \t]*def " + re.escape(name) + r"(?:\[[^\]]*\])?\(", line)), None)
    assert start is not None, f"missing {name} function"
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
            break
        end += 1
    return "\n".join(lines[start:end])


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    types = (root / "src/semantic/semantic_types.elisa").read_text()
    runner = (root / "src/semantic/semantic_parallel.elisa").read_text()
    body = types.split("        struct Diagnostic:\n", 1)[1].split("        # Fresh, empty table.", 1)[0]
    fields = dict(re.findall(r"^            (\w+): (?:mutable )?([^=\n]+)", body, re.M))
    field_types = {name: diagnostic_payload_base_type(kind) for name, kind in fields.items()}
    assert all(kind in {"sview", "u32", "Ast::Pos", "DiagnosticKind"} for kind in field_types.values()), "new Diagnostic payload type requires ownership review"
    texts = [name for name, kind in field_types.items() if kind == "sview"]
    export_texts = [name for name in texts if diagnostic_payload_region(fields[name]) != "@source"]
    parent = runner.split("        def par_pass_parent_diagnostic", 1)[1].split("        def par_pass_worker", 1)[0]
    worker = runner.split("        def par_pass_worker", 1)[1].split("        # True when", 1)[0]
    copies = re.findall(r"table <- par_pass_parent_text\(source\.(\w+), table\)", parent)
    assert len(copies) == len(set(copies)), "duplicate parent text copy"
    assert set(copies) == set(texts), "parent backing copies do not cover exactly the sview fields"
    for label, section in [("parent", parent), ("worker", worker)]:
        literal = diagnostic_literal(section)
        assignments = re.findall(r"^\s*(\w+): ([^\n]+?)(?:,)?$", literal, re.M)
        assert len(assignments) == len(fields), f"{label}: missing or duplicate Diagnostic fields"
        values = dict(assignments)
        assert set(values) == set(fields), f"{label}: Diagnostic field coverage changed"
        for name in fields:
            if name not in texts:
                expected = f"source.{name}"
            elif label == "worker":
                expected = f"par_pass_job_text(&job.arena, source.{name})"
            else:
                expected = f"par_pass_parent_view(table, first + {copies.index(name)})"
            assert normalized_expression(values[name]) == expected, f"{label}: incorrect copy of {name}"
    api = (root / "src/semantic/semantic_api.elisa").read_text()
    exported = function_section(api, "diagnostic_export")
    export_copies = re.findall(r"(\w+): diagnostic_output_text\(source\.(\w+), text_buffers\)", exported)
    assert len(export_copies) == len(export_texts), "export text copies changed"
    assert dict(export_copies) == {name: name for name in export_texts}, "export text mapping changed"
    literal = diagnostic_literal(exported)
    assignments = re.findall(r"^\s*(\w+): ([^\n]+?)(?:,)?$", literal, re.M)
    assert len(assignments) == len(fields), "export Diagnostic field coverage changed"
    values = dict(assignments)
    assert set(values) == set(fields), "export Diagnostic fields changed"
    for name in fields:
        expected = (f"diagnostic_output_text(source.{name}, text_buffers)"
                    if name in export_texts else f"source.{name}")
        assert normalized_expression(values[name]) == expected, f"export: incorrect copy of {name}"
    print(f"parallel Diagnostic ownership audit: {len(fields)} fields, {len(texts)} text payloads covered")


if __name__ == "__main__":
    main()
