#!/usr/bin/env python3
"""Focused load-gate tests; these never start benchmark builds or samples."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("bench_load_gate.py")
spec = importlib.util.spec_from_file_location("bench_load_gate", MODULE_PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class BenchLoadGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.qualification = self.root / "host_qualification.json"

    def write_qualification(self, *, allowed=80, quota=64, qualified=True):
        self.qualification.write_text(json.dumps({
            "system": "Linux",
            "qualified": qualified,
            "allowed_cpu_count": allowed,
            "effective_cgroup_cpu_quota": quota,
        }))

    def test_linux_capacity_uses_minimum_of_affinity_and_quota(self):
        self.write_qualification(allowed=80, quota=64)
        with patch.object(gate.os, "cpu_count", return_value=256):
            capacity, details = gate.effective_cpu_capacity("Linux", self.qualification)
        self.assertEqual(capacity, 64.0)
        self.assertEqual(details["allowed_cpu_count"], 80)
        self.assertEqual(details["cgroup_cpu_quota"], 64.0)

    def test_linux_unlimited_quota_uses_affinity_capacity(self):
        self.write_qualification(allowed=80, quota=None)
        with patch.object(gate.os, "cpu_count", return_value=256):
            capacity, details = gate.effective_cpu_capacity("Linux", self.qualification)
        self.assertEqual(capacity, 80.0)
        self.assertIsNone(details["cgroup_cpu_quota"])

    def test_darwin_keeps_logical_cpu_denominator(self):
        with patch.object(gate.os, "cpu_count", return_value=10):
            capacity, _ = gate.effective_cpu_capacity("Darwin", self.qualification)
        self.assertEqual(capacity, 10.0)
        with patch.object(gate.os, "cpu_count", return_value=10):
            passed = gate.check_load_gate(
                (2.0, 2.0, 2.0), "before sample", self.output, "Darwin", self.qualification,
            )
        self.assertTrue(passed["passed"])
        with patch.object(gate.os, "cpu_count", return_value=10):
            with self.assertRaises(gate.LoadGateError):
                gate.check_load_gate(
                    (2.01, 2.0, 2.0), "after sample", self.output, "Darwin", self.qualification,
                )

    def test_missing_qualification_fails_preflight_closed(self):
        with self.assertRaises(gate.LoadGateError):
            gate.check_load_gate(
                (0.0, 0.0, 0.0), "before builds", self.output, "Linux",
                self.qualification, preflight=True,
            )
        record = json.loads((self.output / "preflight_load_admission.json").read_text())
        self.assertFalse(record["passed"])
        self.assertIn("could not read Linux host qualification", record["capacity_error"])
        self.assertIn("No benchmark builds or timed samples were started", (self.output / "ABORTED.txt").read_text())
        self.assertFalse((self.output / "load_gate_checks.jsonl").exists())

    def test_invalid_qualification_fails_sample_closed(self):
        self.qualification.write_text("[]\n")
        with self.assertRaises(gate.LoadGateError):
            gate.check_load_gate(
                (0.0, 0.0, 0.0), "after sample", self.output, "Linux", self.qualification,
            )
        records = [json.loads(line) for line in (self.output / "load_gate_checks.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["passed"])
        self.assertIn("not a JSON object", records[0]["capacity_error"])
        aborted = (self.output / "ABORTED.txt").read_text()
        self.assertIn("Any partial outputs and measurements", aborted)
        self.assertIn("in-flight sample was allowed to finish", aborted)
        self.assertFalse((self.output / "preflight_load_admission.json").exists())

    def test_load_at_or_below_threshold_passes_and_above_threshold_aborts(self):
        self.write_qualification(allowed=80, quota=64)
        passing = gate.check_load_gate(
            (12.8, 14.0, 16.0), "before sample", self.output, "Linux", self.qualification,
        )
        self.assertTrue(passing["passed"])
        self.assertEqual(passing["effective_cpu_capacity"], 64.0)
        self.assertEqual(passing["load1_limit"], 12.8)
        self.assertFalse((self.output / "ABORTED.txt").exists())

        with self.assertRaises(gate.LoadGateError):
            gate.check_load_gate(
                (12.81, 14.0, 16.0), "after sample", self.output, "Linux", self.qualification,
            )
        records = [json.loads(line) for line in (self.output / "load_gate_checks.jsonl").read_text().splitlines()]
        self.assertEqual([record["passed"] for record in records], [True, False])

    def test_preflight_cli_records_mocked_load(self):
        self.write_qualification(allowed=64, quota=None)
        with patch.object(gate, "load_average", return_value=(1.0, 1.5, 2.0)):
            status = gate.main(["preflight", str(self.output), str(self.qualification), "Linux"])
        self.assertEqual(status, 0)
        record = json.loads((self.output / "preflight_load_admission.json").read_text())
        self.assertEqual(record["load1"], 1.0)
        self.assertEqual(record["effective_cpu_capacity"], 64.0)
        self.assertTrue(record["passed"])


if __name__ == "__main__":
    unittest.main()
