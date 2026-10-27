#!/usr/bin/env python3
"""Safety checks for legal spacing around field-access dots."""
from collections import defaultdict
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import semantic_parallel_gen as audit
from test_semantic_parallel_gen import TABLE_FIELD_TYPES, definition


def classify(body):
    defs = defaultdict(list)
    defs['root'] = [definition('table: mutable SymbolTable&',
        'def root(table: mutable SymbolTable&) -> void:\n    ' + body + '\n')]
    info = audit.analyze(defs, set(), set(), {}, TABLE_FIELD_TYPES, {'SymbolKind': [[]]})
    safe, writes, _ = audit.append_only(info, 'root')
    return safe, writes


class FieldSpacingSafety(unittest.TestCase):
    def test_spacing_cannot_hide_mutation_or_alias(self):
        examples = [
            ('table.duplicates <- 1', ['table . duplicates <- 1', 'table. duplicates <- 1', 'table .duplicates <- 1']),
            ('table.symbols.push(1)', ['table . symbols . push(1)', 'table.symbols .push(1)']),
            ('ptr = &table.symbols', ['ptr = &table . symbols']),
            ('alias: mutable darray[Symbol] = table.symbols\n    alias.push(1)',
             ['alias: mutable darray[Symbol] = table . symbols\n    alias . push(1)']),
            ('value = table.diagnostics', ['value = table . diagnostics']),
        ]
        for compact, variants in examples:
            expected = classify(compact)
            self.assertFalse(expected[0], (compact, expected))
            for spaced in variants:
                with self.subTest(spaced=spaced):
                    self.assertEqual(classify(spaced), expected)

    def test_literals_and_interpolation(self):
        text = 'a = "table . symbols"\nb = f"keep x . y {table . duplicates}"\nc = "hello" . len\n'
        normalized, masked = audit.audit_normalize_field_dots(text)
        self.assertIn('"table . symbols"', normalized)
        self.assertIn('keep x . y {table.duplicates}', normalized)
        self.assertIn('"hello" . len', normalized)
        self.assertIn('table.duplicates', masked)
        self.assertEqual(len(normalized), len(masked))

    def test_compact_paths_are_unchanged(self):
        text = 'table.symbols[0].value <- 1\n'
        normalized, masked = audit.audit_normalize_field_dots(text)
        self.assertEqual(normalized, text)
        self.assertEqual(len(normalized), len(masked))


if __name__ == '__main__':
    unittest.main()
