#!/usr/bin/env python3
"""Differential checks for conservative global-name scanning in the audit."""

import random
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semantic_parallel_gen as audit


class TokenScanParityTests(unittest.TestCase):
    def test_randomized_word_boundaries_and_callable_paths(self):
        randomizer = random.Random(19817)
        names = ["x", "a", "a_b", "1", "α", "d3", "a.b", "", "_", "!", "x-y", "h 2"]
        pieces = ["x", "a", "a_b", "1", "α", "d3", "a.b", "(", ")", "[i]", "  ", "-", "_", ":", "\n", '"x"', "!", "x-y"]
        for case in range(5000):
            text = "".join(randomizer.choices(pieces, k=randomizer.randrange(25)))
            globals_ = set(randomizer.sample(names, randomizer.randrange(len(names) + 1)))
            aliases = set(randomizer.sample(names, randomizer.randrange(len(names) + 1)))
            expected = {
                name for name in globals_
                if re.search(r"\b" + re.escape(name) + r"\b", text)
            }
            if any(re.search(r"\b" + re.escape(name) + r"\b", text) for name in aliases):
                expected.add("aliased-global")
            with self.subTest(case=case, text=text):
                self.assertEqual(audit.argument_global_names(text, globals_, aliases), expected)
                expected_callable = {
                    name for name in globals_ | aliases
                    for match in re.finditer(r"\b" + re.escape(name) + r"\b", text)
                    if audit.global_path_is_invoked(text, match.end())
                }
                self.assertEqual(audit._global_callable_names(text, globals_ | aliases), expected_callable)


if __name__ == "__main__":
    unittest.main()
