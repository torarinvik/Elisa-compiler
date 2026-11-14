#!/usr/bin/env python3
"""Ensure private-branch proof admission follows indexed wrappers and row walkers."""
import contextlib
import io
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CONSUMER = ROOT / 'src/semantic/check_private_member_access.elisa'
GATE = ROOT / 'test/proofs/check_private_module_boundary.py'


class PrivateBranchProofBinding(unittest.TestCase):
    def admission(self, old=None, new=None):
        original_read = Path.read_text
        source = original_read(CONSUMER)
        if old is not None:
            self.assertIn(old, source)
            source = source.replace(old, new, 1)

        def read(path, *args, **kwargs):
            return source if path == CONSUMER else original_read(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read), patch.object(sys, 'argv', [str(GATE), '--source-only']), patch.object(sys, 'path', [str(GATE.parent)] + sys.path), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(GATE), run_name='__main__')
        return result.exception.code

    def test_current_source_admitted(self):
        self.assertEqual(self.admission(), 0)

    def test_incomplete_projection_and_walkers_rejected(self):
        changes = [
            ('table.static_if_branch_source_count == file.enum_annotations.count and file.enum_annotations.count > 0', 'true'),
            ('pma_static_if_const_branch_rows(file.enum_annotations, file, name, symbol, table, depth)', 'pma_static_if_const_branch_rows(table.static_if_branch_annotations, file, name, symbol, table, depth)'),
            ('marker.offset != symbol.offset', 'marker.offset != 0'),
            ('return (false, false) if unknown', 'return (true, true) if unknown'),
            ('if annotation.owner == "__static_if_branch":', 'if annotation.owner == "wrong":'),
            ('static_if_branch_heads.get(symbol.offset)', 'static_if_branch_heads.get(symbol.line)'),
            ('static_if_branch_next.push(previous)', 'static_if_branch_next.push(row)'),
        ]
        for old, new in changes:
            with self.subTest(change=old):
                self.assertNotEqual(self.admission(old, new), 0)


if __name__ == '__main__':
    unittest.main()
