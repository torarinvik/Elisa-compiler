#!/usr/bin/env python3
"""Reject omitted or miscopied fields in parallel Diagnostic ownership transfers."""
from pathlib import Path
import re


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    types = (root / "src/semantic/semantic_types.elisa").read_text()
    runner = (root / "src/semantic/semantic_parallel.elisa").read_text()
    body = types.split("        struct Diagnostic:\n", 1)[1].split("        # Fresh, empty table.", 1)[0]
    fields = dict(re.findall(r"^            (\w+): (?:mutable )?([^=\n]+)", body, re.M))
    texts = [name for name, kind in fields.items() if kind.strip() == "sview"]
    parent = runner.split("        def par_pass_parent_diagnostic", 1)[1].split("        def par_pass_worker", 1)[0]
    worker = runner.split("        def par_pass_worker", 1)[1].split("        # True when", 1)[0]
    copies = re.findall(r"table <- par_pass_parent_text\(source\.(\w+), table\)", parent)
    assert len(copies) == len(set(copies)), "duplicate parent text copy"
    assert set(copies) == set(texts), "parent backing copies do not cover exactly the sview fields"
    for label, section in [("parent", parent), ("worker", worker)]:
        literal = section.split("Diagnostic{", 1)[1].split("}", 1)[0]
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
            assert values[name].rstrip(",") == expected, f"{label}: incorrect copy of {name}"
    print(f"parallel Diagnostic ownership audit: {len(fields)} fields, {len(texts)} text payloads covered")


if __name__ == "__main__":
    main()
