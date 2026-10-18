import math
import os
import sys
import time
import unittest

from paired import (
    DarwinProcessCounters,
    counter_delta,
    mach_ticks_to_ns,
    memory_observation,
    paired_counter_measurements,
    paired_timing_summary,
    timing_arm_kinds,
)


class PairedTimingSummaryTest(unittest.TestCase):
    def test_memory_gauges_can_decrease_without_counter_failure(self) -> None:
        before = {"physical_footprint_bytes": 120, "lifetime_max_physical_footprint_bytes": 180}
        after = {"physical_footprint_bytes": 100, "lifetime_max_physical_footprint_bytes": 190}
        observation = memory_observation(before, after)
        self.assertEqual(observation["physical_footprint_change_bytes"], -20)
        before["physical_footprint_bytes"] = 999
        self.assertEqual(observation["before"]["physical_footprint_bytes"], 120)
        with self.assertRaises(RuntimeError):
            counter_delta({"instructions_retired": 120}, {"instructions_retired": 100})

    def test_converts_mach_ticks_with_integer_precision(self) -> None:
        self.assertEqual(mach_ticks_to_ns(3, 125, 3), 125)
        self.assertEqual(mach_ticks_to_ns(1, 125, 3), 41)
        self.assertEqual(mach_ticks_to_ns(123, 1, 1), 123)
        self.assertEqual(mach_ticks_to_ns(2**63, 125, 3), 2**63 * 125 // 3)
        for values in [(-1, 1, 1), (1, 0, 1), (1, 1, 0)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                mach_ticks_to_ns(*values)

    def test_reports_paired_median_geomean_and_wins(self) -> None:
        summary = paired_timing_summary([0.8, 1.25, 1.0], "fixture control")

        self.assertEqual(summary["median_paired_graph_on_over_off_ratio"], 1.0)
        self.assertTrue(math.isclose(summary["geometric_mean_paired_graph_on_over_off_ratio"], 1.0))
        self.assertEqual(summary["paired_graph_on_wins"], 1)
        self.assertEqual(summary["paired_graph_off_wins"], 1)
        self.assertEqual(summary["paired_ties"], 1)
        self.assertEqual(summary["paired_request_ratios"], [0.8, 1.25, 1.0])

    def test_rejects_empty_or_invalid_pairs(self) -> None:
        for ratios in ([], [0.0], [float("nan")], [float("inf")]):
            with self.subTest(ratios=ratios), self.assertRaises(RuntimeError):
                paired_timing_summary(ratios, "fixture control")

    def test_counterbalances_routing_and_timing_arm_order(self) -> None:
        self.assertEqual(timing_arm_kinds(0), (True, False))
        self.assertEqual(timing_arm_kinds(1), (False, True))
        self.assertEqual(timing_arm_kinds(2), (True, False))

    def test_summarizes_paired_process_counters(self) -> None:
        arms = [
            {"pair": 0, "mode": "graph-off", "requests": [{"label": "edit", "instructions_retired": 100}]},
            {"pair": 0, "mode": "graph-on", "requests": [{"label": "edit", "instructions_retired": 80}]},
            {"pair": 1, "mode": "graph-off", "requests": [{"label": "edit", "instructions_retired": 120}]},
            {"pair": 1, "mode": "graph-on", "requests": [{"label": "edit", "instructions_retired": 132}]},
        ]

        summary = paired_counter_measurements(arms, 2, ["edit"], "instructions_retired", "fixture")

        self.assertEqual(summary["per_label"]["edit"]["graph_off_median"], 110)
        self.assertEqual(summary["per_label"]["edit"]["graph_on_median"], 106)
        self.assertEqual(summary["paired_aggregate"]["paired_request_ratios"], [0.8, 1.1])

    @unittest.skipUnless(sys.platform == "darwin", "macOS process counters are Darwin-specific")
    def test_reads_retired_instructions_for_current_process(self) -> None:
        counters = DarwinProcessCounters()
        before = counters.snapshot(os.getpid())
        checksum = sum(index ^ (index >> 3) for index in range(50_000))
        after = counters.snapshot(os.getpid())

        delta = counter_delta(before, after)
        self.assertGreater(delta["instructions_retired"], 0)
        self.assertGreater(delta["cycles_elapsed"], 0)
        self.assertGreater(checksum, 0)

    @unittest.skipUnless(sys.platform == "darwin", "macOS process counters are Darwin-specific")
    def test_process_cpu_time_uses_nanoseconds(self) -> None:
        counters = DarwinProcessCounters()
        start = time.process_time_ns()
        before = counters.snapshot(os.getpid())
        checksum = sum((index * index) ^ (index >> 3) for index in range(600_000))
        after = counters.snapshot(os.getpid())
        elapsed = time.process_time_ns() - start
        measured = counter_delta(before, after)["cpu_time_ns"]
        # The reads include slightly different Python/syscall overhead. This
        # checks units, not timing performance or exact scheduling equivalence.
        self.assertGreater(measured / elapsed, 0.8)
        self.assertLess(measured / elapsed, 1.2)
        self.assertGreater(checksum, 0)

    @unittest.skipUnless(sys.platform == "darwin", "macOS process gauges are Darwin-specific")
    def test_reads_process_memory_gauges_separately(self) -> None:
        counters, memory = DarwinProcessCounters().snapshot_with_memory(os.getpid())
        self.assertEqual(set(counters), {"instructions_retired", "cycles_elapsed", "cpu_time_ns"})
        self.assertGreater(memory["physical_footprint_bytes"], 0)
        self.assertGreater(memory["lifetime_max_physical_footprint_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
