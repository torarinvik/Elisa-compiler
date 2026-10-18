import math
import os
import sys
import unittest

from paired import (
    DarwinProcessCounters,
    counter_delta,
    paired_counter_measurements,
    paired_timing_summary,
    timing_arm_kinds,
)


class PairedTimingSummaryTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
