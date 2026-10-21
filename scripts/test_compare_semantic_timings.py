#!/usr/bin/env python3
"""Protect phase attribution when timed compiler runs are truncated."""
import unittest
from compare_semantic_timings import parse_profile


class TimingAttributionTest(unittest.TestCase):
    def test_quiet_summary_uses_historical_report_label(self):
        profile = parse_profile('''stage1-timing: sem:collect_range wall_ms=10.0 cpu_ms=9.0
stage1-timing: authority:collect_setup wall_ms=20.0 cpu_ms=19.0
stage1-counter: authority:report_functions_progress count=1024
stage1-counter: authority:report_functions_progress count=2048
stage1-counter: authority:report_functions_progress count=1024
real 30.29
''')
        self.assertEqual(profile.preauthority, [10.0, 9.0])
        self.assertEqual(profile.progress['summary'], [2048, 1024])
        self.assertNotIn('report', profile.progress)
        self.assertIn('no end row', profile.unfinished)
        self.assertNotIn('authority:return_summaries', profile.phases)

    def test_finished_summary_changes_counter_attribution(self):
        profile = parse_profile('''stage1-timing: authority:collect_setup wall_ms=20.0 cpu_ms=19.0
stage1-counter: authority:report_functions_progress count=1024
stage1-timing: authority:return_summaries wall_ms=200.0 cpu_ms=190.0
stage1-counter: authority:inference_functions_progress count=1024
stage1-timing: authority:inference_walk wall_ms=300.0 cpu_ms=290.0
stage1-counter: authority:report_functions_progress count=1024
stage1-timing: authority:report_walk wall_ms=400.0 cpu_ms=390.0
stage1-timing: sem:check_mutable_global_authority wall_ms=950.0 cpu_ms=900.0
''')
        self.assertEqual(dict(profile.progress), {'summary': [1024], 'inference': [1024], 'report': [1024]})
        self.assertEqual(profile.preauthority, [0.0, 0.0])
        self.assertEqual(profile.unfinished, 'authority completed')

    def test_round_span_does_not_mark_entire_summary_complete(self):
        profile = parse_profile('''stage1-timing: authority:collect_setup wall_ms=20.0 cpu_ms=19.0
stage1-counter: authority:report_functions_progress count=1024
stage1-timing: authority:return_summary_round wall_ms=50.0 cpu_ms=49.0
stage1-counter: authority:return_summary_rounds count=1
stage1-counter: authority:report_functions_progress count=1024
stage1-timing: authority:return_summary_round wall_ms=10.0 cpu_ms=9.0
''')
        self.assertEqual(profile.progress['summary'], [1024, 1024])
        self.assertEqual(profile.phases['authority:return_summary_round'], [60.0, 58.0])
        self.assertEqual(profile.summary_round_wall, [50.0, 10.0])
        self.assertIn('no end row', profile.unfinished)

    def test_only_sequential_sem_rows_enter_preauthority_subtotal(self):
        profile = parse_profile('''stage1-timing: sem:one wall_ms=10.0 cpu_ms=9.0
stage1-timing: nested:span wall_ms=8.0 cpu_ms=7.0
stage1-timing: sem:one wall_ms=2.0 cpu_ms=1.0
stage1-timing: authority:collect_setup wall_ms=20.0 cpu_ms=19.0
stage1-timing: sem:check_global_authority wall_ms=50.0 cpu_ms=49.0
''')
        self.assertEqual(profile.preauthority, [12.0, 10.0])
        self.assertEqual(profile.phases['sem:one'], [12.0, 10.0])


if __name__ == '__main__':
    unittest.main()
