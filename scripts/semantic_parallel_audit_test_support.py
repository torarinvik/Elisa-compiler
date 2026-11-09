#!/usr/bin/env python3
"""Focused soundness and precision checks for the semantic parallel audit."""
from collections import defaultdict
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semantic_parallel_gen as audit
import semantic_parallel_diagnostic_audit as diagnostic_audit


TABLE_FIELD_TYPES = {
    "diagnostics": "mutable darray[Diagnostic]",
    "symbols": "mutable darray[Symbol]",
    "duplicates": "mutable u32",
    "pointer_bits": "uintptr",
}


def definition(params, body, external=False):
    lines = body.splitlines(keepends=True)
    return_type = ""
    if lines:
        match = re.search(r"\)\s*->\s*([^:\n]+)\s*:", lines[0])
        if match:
            return_type = match.group(1).strip()
    return {
        "params": params,
        "return_type": return_type,
        "body": lines,
        "external": external,
    }


def analyze(
    definitions, globals_=(), table_field_types=None, struct_field_types=None, type_aliases=None,
    enum_variants=None,
):
    defs = defaultdict(list)
    defs.update(definitions)
    return audit.analyze(
        defs, set(globals_), set(), type_aliases or {}, table_field_types or TABLE_FIELD_TYPES,
        struct_field_types or {"SymbolKind": [[]]}, enum_variants or {},
    )


