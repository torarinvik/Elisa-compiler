"""Focused checks for cross-language benchmark preflight helpers."""
from pathlib import Path
import unittest

import benchmark_fingerprint
import benchmark_preflight


class BenchmarkHelperTests(unittest.TestCase):
    def test_preflight_checks_every_variant_and_rejects_wrong_checksum(self):
        calls = []
        context = {
            "benches": ["sum"], "variants": ["native", "elisa"],
            "out": Path("/bench"), "expected_checksums": {"sum": 42},
            "expected_exit_statuses": {"sum": 0},
            "run_once": lambda binary: (calls.append(binary) or (0, b"42\n", b"")),
            "mark_aborted": lambda kind, message: (_ for _ in ()).throw(RuntimeError(message)),
        }
        self.assertEqual(benchmark_preflight.correctness_preflight(context, "check"),
                         {"sum": {"checksum": "42\n", "exit_status": 0}})
        self.assertEqual(calls, [Path("/bench/sum/native"), Path("/bench/sum/elisa")])
        context["run_once"] = lambda binary: (0, b"wrong\n", b"")
        with self.assertRaisesRegex(RuntimeError, "expected exact checksum"):
            benchmark_preflight.correctness_preflight(context, "check")

    def test_environment_input_names_include_elisa_overrides(self):
        context = {"ENVIRONMENT_INPUT_NAMES": ("PATH",),
                   "environment_input_hashes": lambda env, names: names}
        self.assertEqual(benchmark_fingerprint.run_environment_input_hashes(
            context, {"ELISA_EXAMPLE": "x", "UNRELATED": "y"}),
            ["ELISA_EXAMPLE", "PATH"])


if __name__ == "__main__":
    unittest.main()
