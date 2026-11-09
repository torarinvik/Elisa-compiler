"""Verify semantic pipeline fragment expansion and safe regeneration."""
from pathlib import Path
import tempfile
import unittest

from semantic_pipeline_source import BEGIN, DIRECTIVE, END, FRAGMENT, read_pipeline_source, write_pipeline_source


class SemanticPipelineSourceTests(unittest.TestCase):
    def test_round_trip_preserves_fragment_and_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "full_pipeline.elisa"
            fragment = root.parent / FRAGMENT
            root_text = "extend Semantic:\n" + DIRECTIVE + "\n    end\n"
            fragment_text = "        first\n        second\n"
            root.write_text(root_text)
            fragment.write_text(fragment_text)
            expanded = read_pipeline_source(root, annotated=True)
            self.assertIn(BEGIN, expanded)
            self.assertIn(END, expanded)
            self.assertNotIn(DIRECTIVE, expanded)
            write_pipeline_source(root, expanded)
            self.assertEqual(root.read_text(), root_text)
            self.assertEqual(fragment.read_text(), fragment_text)
            self.assertEqual(read_pipeline_source(root), root_text.replace(DIRECTIVE, fragment_text.rstrip("\n")))

    def test_missing_boundary_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "full_pipeline.elisa"
            fragment = root.parent / FRAGMENT
            root.write_text(DIRECTIVE + "\n")
            fragment.write_text("        original\n")
            with self.assertRaisesRegex(ValueError, "lost its fragment boundary"):
                write_pipeline_source(root, "rewritten\n")
            self.assertEqual(root.read_text(), DIRECTIVE + "\n")
            self.assertEqual(fragment.read_text(), "        original\n")


if __name__ == "__main__":
    unittest.main()
