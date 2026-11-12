#!/usr/bin/env python3
"""Exercise the seed wall-time runner without invoking either compiler stage."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import run_with_timeout


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_with_timeout.py"


class RunWithTimeoutTests(unittest.TestCase):
    def test_deadline_race_with_exited_group(self) -> None:
        process = Mock(pid=123)
        process.wait.return_value = 75
        process.poll.return_value = 75
        with (
            patch.object(run_with_timeout.subprocess, "Popen", return_value=process),
            patch.object(run_with_timeout.signal, "signal"),
            patch.object(run_with_timeout, "_wait_for_exit", side_effect=subprocess.TimeoutExpired(["compiler"], 5)),
            patch.object(run_with_timeout.os, "killpg", side_effect=[PermissionError(), ProcessLookupError()]),
        ):
            self.assertEqual(run_with_timeout.run(["compiler"], 5), 124)
        process.kill.assert_called_once()

    def test_deadline_reports_permission_denied_for_live_child(self) -> None:
        process = Mock(pid=123)
        process.wait.side_effect = subprocess.TimeoutExpired(["compiler"], 5)
        process.poll.return_value = None
        with (
            patch.object(run_with_timeout.subprocess, "Popen", return_value=process),
            patch.object(run_with_timeout.signal, "signal"),
            patch.object(run_with_timeout, "_wait_for_exit", side_effect=subprocess.TimeoutExpired(["compiler"], 5)),
            patch.object(run_with_timeout.os, "killpg", side_effect=PermissionError()),
        ):
            self.assertEqual(run_with_timeout.run(["compiler"], 5), 125)
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=0.05)

    def test_timeout_terminates_owned_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "child-finished"
            child = (
                "import pathlib,sys,time; time.sleep(0.6); "
                "pathlib.Path(sys.argv[1]).write_text('alive')"
            )
            parent = (
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
                "time.sleep(10)"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "0.1",
                    "--",
                    sys.executable,
                    "-c",
                    parent,
                    child,
                    str(marker),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(result.returncode, 124, result.stderr)
            self.assertIn("deadline exceeded (0.1s)", result.stderr)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "a descendant survived the process-group timeout")

    def test_parent_signal_terminates_nested_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "nested-child-finished"
            child = (
                "import pathlib,sys,time; time.sleep(0.6); "
                "pathlib.Path(sys.argv[1]).write_text('alive')"
            )
            parent = (
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
                "time.sleep(10)"
            )
            wrapper = subprocess.Popen(
                [
                    sys.executable,
                    str(RUNNER),
                    "10",
                    "--",
                    sys.executable,
                    "-c",
                    parent,
                    child,
                    str(marker),
                ],
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(0.1)
            os.killpg(wrapper.pid, signal.SIGTERM)
            stdout, stderr = wrapper.communicate(timeout=5)
            self.assertEqual(wrapper.returncode, 128 + signal.SIGTERM, stderr or stdout)
            time.sleep(0.7)
            self.assertFalse(marker.exists(), "a nested descendant survived the parent signal")

    def test_signal_exit_status_is_preserved(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RUNNER), "2", "--", sys.executable, "-c", "raise SystemExit(23)"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(result.returncode, 23, result.stderr)

    def test_missing_command_is_distinct(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RUNNER), "2", "--", str(Path(tempfile.gettempdir()) / "not-a-command")],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(result.returncode, 127, result.stderr)

    def test_stage1_seed_entrypoint_has_a_fixed_direct_deadline(self) -> None:
        entrypoint = (ROOT / "scripts" / "elisac_stage1.sh").read_text(encoding="utf-8")
        self.assertIn('"$ROOT/scripts/run_with_timeout.py" 3 --', entrypoint)
        self.assertIn('ELISA_STAGE1_SEED_TIMEOUT_WRAPPED:-0', entrypoint)


if __name__ == "__main__":
    unittest.main(verbosity=2)
