#!/usr/bin/env python3
"""Focused load-gate tests; these never start benchmark builds or samples."""

import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack
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
            "allowed_cpu_ids": list(range(allowed)),
            "effective_cgroup_cpu_quota": quota,
        }))

    def write_live_qualification(self):
        quota_path = self.root / "cpu.max"
        quota_path.write_text("6400000 100000\n")
        mountinfo = b"test cgroup mount layout\n"
        membership_lines = ["0::/benchmark"]
        namespace = {"self": "cgroup:[123]", "init": "cgroup:[123]"}
        self.qualification.write_text(json.dumps({
            "system": "Linux",
            "machine": "x86_64",
            "qualified": True,
            "allowed_cpu_count": 80,
            "allowed_cpu_ids": list(range(80)),
            "effective_cgroup_cpu_quota": 64.0,
            "cgroup_quota_sources": [{
                "quota_path": str(quota_path),
                "quota": 6400000,
                "period": 100000,
                "cpus": 64.0,
            }],
            "cgroup_membership_lines": membership_lines,
            "cgroup_mountinfo_sha256": hashlib.sha256(mountinfo).hexdigest(),
            "cgroup_namespace": namespace,
        }))
        return {
            "quota_path": quota_path,
            "mountinfo": mountinfo,
            "membership_lines": membership_lines,
            "namespace": namespace,
        }

    def patch_live_linux_state(self, stack, state, *, affinity=80, affinity_ids=None, membership_lines=None):
        original_read_text = Path.read_text
        original_read_bytes = Path.read_bytes
        original_readlink = gate.os.readlink

        def read_text(path, *args, **kwargs):
            if str(path) == "/proc/self/cgroup":
                return "\n".join(membership_lines if membership_lines is not None else state["membership_lines"]) + "\n"
            return original_read_text(path, *args, **kwargs)

        def read_bytes(path, *args, **kwargs):
            if str(path) == "/proc/self/mountinfo":
                return state["mountinfo"]
            return original_read_bytes(path, *args, **kwargs)

        def readlink(path, *args, **kwargs):
            if str(path) == "/proc/self/ns/cgroup":
                return state["namespace"]["self"]
            if str(path) == "/proc/1/ns/cgroup":
                return state["namespace"]["init"]
            return original_readlink(path, *args, **kwargs)

        live_affinity = set(range(affinity)) if affinity_ids is None else set(affinity_ids)
        stack.enter_context(patch.object(gate.os, "sched_getaffinity", return_value=live_affinity, create=True))
        stack.enter_context(patch.object(gate.platform, "machine", return_value="x86_64"))
        stack.enter_context(patch.object(Path, "read_text", read_text))
        stack.enter_context(patch.object(Path, "read_bytes", read_bytes))
        stack.enter_context(patch.object(gate.os, "readlink", readlink))

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

    def test_live_linux_capacity_accepts_matching_snapshot(self):
        state = self.write_live_qualification()
        with ExitStack() as stack:
            self.patch_live_linux_state(stack, state)
            record = gate.check_load_gate(
                (12.8, 14.0, 16.0), "live Linux sample", self.output, "Linux",
                self.qualification, require_live_linux=True,
            )
        self.assertTrue(record["passed"])
        self.assertEqual(record["effective_cpu_capacity"], 64.0)
        self.assertEqual(record["live_allowed_cpu_count"], 80)
        self.assertEqual(record["live_allowed_cpu_ids"], list(range(80)))
        self.assertEqual(record["live_cgroup_cpu_quota"], 64.0)

    def test_live_linux_capacity_aborts_when_affinity_changes(self):
        state = self.write_live_qualification()
        with ExitStack() as stack:
            self.patch_live_linux_state(stack, state, affinity=79)
            with self.assertRaises(gate.LoadGateError):
                gate.check_load_gate(
                    (0.0, 0.0, 0.0), "changed Linux affinity", self.output, "Linux",
                    self.qualification, require_live_linux=True,
                )
        self.assertIn("affinity set", (self.output / "ABORTED.txt").read_text())

        same_count_output = self.root / "same-count-affinity-output"
        same_count_output.mkdir()
        with ExitStack() as stack:
            self.patch_live_linux_state(stack, state, affinity_ids=set(range(1, 81)))
            with self.assertRaises(gate.LoadGateError):
                gate.check_load_gate(
                    (0.0, 0.0, 0.0), "same-count changed Linux affinity", same_count_output, "Linux",
                    self.qualification, require_live_linux=True,
                )
        self.assertIn("affinity set", (same_count_output / "ABORTED.txt").read_text())

    def test_live_linux_capacity_aborts_when_membership_or_quota_changes(self):
        state = self.write_live_qualification()
        membership_output = self.root / "membership-output"
        membership_output.mkdir()
        with ExitStack() as stack:
            self.patch_live_linux_state(stack, state, membership_lines=["0::/different"])
            with self.assertRaises(gate.LoadGateError):
                gate.check_load_gate(
                    (0.0, 0.0, 0.0), "changed Linux cgroup", membership_output, "Linux",
                    self.qualification, require_live_linux=True,
                )
        self.assertIn("membership differs", (membership_output / "ABORTED.txt").read_text())

        quota_output = self.root / "quota-output"
        quota_output.mkdir()
        state["quota_path"].write_text("6300000 100000\n")
        with ExitStack() as stack:
            self.patch_live_linux_state(stack, state)
            with self.assertRaises(gate.LoadGateError):
                gate.check_load_gate(
                    (0.0, 0.0, 0.0), "changed Linux quota", quota_output, "Linux",
                    self.qualification, require_live_linux=True,
                )
        self.assertIn("quota changed", (quota_output / "ABORTED.txt").read_text())


class FakeClock:
    def __init__(self, extra_sleep=None):
        self.now = 0.0
        self.sleep_count = 0
        self.extra_sleep = extra_sleep or {}

    def monotonic(self):
        return self.now

    def time(self):
        return 1_800_000_000.0 + self.now

    def sleep(self, seconds):
        self.sleep_count += 1
        self.now += seconds + self.extra_sleep.get(self.sleep_count, 0.0)


class SustainedLoadGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.qualification = self.root / "host_qualification.json"

    def test_high_sample_resets_the_full_stable_window(self):
        loads = iter([
            (2.0, 0.0, 0.0),
            (1.9, 0.0, 0.0),
            (2.01, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
        ])
        clock = FakeClock()
        with patch.object(gate, "effective_cpu_capacity", return_value=(10.0, {"logical_cpu_count": 10})):
            with patch.object(gate, "load_average", side_effect=lambda: next(loads)):
                with patch.object(gate, "time", clock):
                    result = gate.wait_for_sustained_load_gate(
                        self.output,
                        "Darwin",
                        self.qualification,
                        stable_seconds=2.0,
                        sample_interval_seconds=1.0,
                        max_wait_seconds=10.0,
                    )

        self.assertEqual(result["sample_count"], 6)
        self.assertEqual(result["consecutive_below_limit_seconds"], 2.0)
        records = [
            json.loads(line)
            for line in (self.output / "load_gate_sustained_admission.jsonl").read_text().splitlines()
        ]
        self.assertFalse(records[2]["passed"])
        self.assertTrue(records[-1]["sustained_gate_passed"])
        self.assertTrue((self.output / "load_gate_sustained_admission.json").is_file())
        self.assertFalse((self.output / "ABORTED.txt").exists())

    def test_missed_sample_interval_resets_the_stable_window(self):
        clock = FakeClock(extra_sleep={2: 1.0})
        with patch.object(gate, "effective_cpu_capacity", return_value=(10.0, {"logical_cpu_count": 10})):
            with patch.object(gate, "load_average", return_value=(1.0, 0.0, 0.0)):
                with patch.object(gate, "time", clock):
                    result = gate.wait_for_sustained_load_gate(
                        self.output,
                        "Darwin",
                        self.qualification,
                        stable_seconds=2.0,
                        sample_interval_seconds=1.0,
                        max_wait_seconds=10.0,
                    )

        self.assertEqual(result["sample_count"], 5)
        records = [
            json.loads(line)
            for line in (self.output / "load_gate_sustained_admission.jsonl").read_text().splitlines()
        ]
        self.assertEqual(records[2]["consecutive_below_limit_seconds"], 0.0)

    def test_timeout_aborts_before_timed_samples(self):
        clock = FakeClock()
        with patch.object(gate, "effective_cpu_capacity", return_value=(10.0, {"logical_cpu_count": 10})):
            with patch.object(gate, "load_average", return_value=(3.0, 0.0, 0.0)):
                with patch.object(gate, "time", clock):
                    with self.assertRaises(gate.LoadGateError):
                        gate.wait_for_sustained_load_gate(
                            self.output,
                            "Darwin",
                            self.qualification,
                            stable_seconds=2.0,
                            sample_interval_seconds=1.0,
                            max_wait_seconds=2.0,
                        )

        self.assertIn("No timed benchmark samples were started", (self.output / "ABORTED.txt").read_text())
        self.assertEqual(
            len((self.output / "load_gate_sustained_admission.jsonl").read_text().splitlines()),
            3,
        )

    def test_late_poll_cannot_admit_after_max_wait(self):
        clock = FakeClock(extra_sleep={2: 0.6})
        with patch.object(gate, "effective_cpu_capacity", return_value=(10.0, {"logical_cpu_count": 10})):
            with patch.object(gate, "load_average", return_value=(1.0, 0.0, 0.0)):
                with patch.object(gate, "time", clock):
                    with self.assertRaises(gate.LoadGateError):
                        gate.wait_for_sustained_load_gate(
                            self.output,
                            "Darwin",
                            self.qualification,
                            stable_seconds=1.5,
                            sample_interval_seconds=1.0,
                            max_wait_seconds=1.5,
                        )

        records = [
            json.loads(line)
            for line in (self.output / "load_gate_sustained_admission.jsonl").read_text().splitlines()
        ]
        self.assertTrue(records[-1]["passed"])
        self.assertGreater(records[-1]["consecutive_below_limit_seconds"], 1.5)
        self.assertFalse(records[-1]["sustained_gate_passed"])
        self.assertIn("No timed benchmark samples were started", (self.output / "ABORTED.txt").read_text())

    def test_live_linux_sustained_admission_revalidates_capacity(self):
        state = BenchLoadGateTests.write_live_qualification(self)
        clock = FakeClock()
        with ExitStack() as stack:
            BenchLoadGateTests.patch_live_linux_state(self, stack, state)
            stack.enter_context(patch.object(gate, "load_average", return_value=(12.8, 0.0, 0.0)))
            stack.enter_context(patch.object(gate, "time", clock))
            result = gate.wait_for_sustained_load_gate(
                self.output,
                "Linux",
                self.qualification,
                stable_seconds=1.0,
                sample_interval_seconds=1.0,
                max_wait_seconds=2.0,
                require_live_linux=True,
            )

        self.assertEqual(result["effective_cpu_capacity"], 64.0)
        self.assertEqual(result["live_allowed_cpu_count"], 80)
        self.assertEqual(result["live_allowed_cpu_ids"], list(range(80)))
        self.assertEqual(result["live_cgroup_cpu_quota"], 64.0)
        self.assertTrue(result["sustained_gate_passed"])
        records = [
            json.loads(line)
            for line in (self.output / "load_gate_sustained_admission.jsonl").read_text().splitlines()
        ]
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["passed"] for record in records))


if __name__ == "__main__":
    unittest.main()
