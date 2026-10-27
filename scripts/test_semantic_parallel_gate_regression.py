#!/usr/bin/env python3
"""Regression for fail-closed scheduling of stale append-only pass IDs."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import semantic_parallel_gen as audit

ROOT = Path(__file__).resolve().parent.parent
UNSAFE = {15, 80, 90, 91, 92, 98, 120, 126, 162, 196}


def read_gate_ids(source):
    start = source.index(audit.PARALLEL_GATE_BEGIN)
    end = source.index(audit.PARALLEL_GATE_END, start)
    block = source[start:end]
    ids = set()
    for line in block.splitlines():
        span = re.fullmatch(r'\s*return true if pass_id >= (\d+) and pass_id <= (\d+)', line)
        singleton = re.fullmatch(r'\s*return true if pass_id == (\d+)', line)
        prefix = re.fullmatch(r'\s*return true if pass_id <= (\d+)', line)
        if span:
            ids.update(range(int(span[1]), int(span[2]) + 1))
        elif singleton:
            ids.add(int(singleton[1]))
        elif prefix:
            ids.update(range(int(prefix[1]) + 1))
        elif 'return true' in line:
            raise AssertionError('unrecognized gate clause: ' + line)
    return ids


class ParallelGateRegression(unittest.TestCase):
    def test_unsafe_ids_decline_and_neighbors_remain_eligible(self):
        source = (ROOT / 'src/semantic/semantic_parallel_passes.elisa').read_text()
        ids = read_gate_ids(source)
        self.assertFalse(ids & UNSAFE, f'unsafe IDs admitted: {sorted(ids & UNSAFE)}')
        self.assertTrue({14, 16, 79, 81, 89, 93, 97, 99, 119, 121, 125, 163, 195, 197} <= ids)
        self.assertEqual(audit.parallel_safety_gate_errors(source, ids), [])

    def test_runtime_checks_whole_batch_before_worker_submission(self):
        runtime = (ROOT / 'src/semantic/semantic_parallel.elisa').read_text()
        self.assertEqual(audit.parallel_runtime_serial_guard_errors(runtime), [])
        pipeline = (ROOT / 'src/semantic/semantic_api/full_pipeline.elisa').read_text()
        self.assertRegex(pipeline, r'par_pass_run\(file, flags, table, shared_pool, loop_view, 80, 5\)')
        self.assertTrue(any(i in UNSAFE for i in range(80, 85)))


if __name__ == '__main__':
    unittest.main()
