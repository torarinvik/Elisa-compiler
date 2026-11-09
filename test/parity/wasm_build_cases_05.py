from __future__ import annotations

from wasm_build_test_support import *


class BoundedStage1CommandTests(unittest.TestCase):
    def test_rss_limit_accepts_the_configured_boundary(self) -> None:
        with patch.dict(os.environ, {"ELISA_STAGE1_MAX_RSS_KB": "2097152"}, clear=True):
            self.assertEqual(bounded_runner.rss_limit_kb(), 2097152)

    def test_rss_limit_fails_closed_for_missing_invalid_and_excessive_values(self) -> None:
        for value, expected_status in (("", 125), ("not-a-number", 125), ("2097153", 2)):
            with self.subTest(value=value):
                with (
                    patch.dict(os.environ, {"ELISA_STAGE1_MAX_RSS_KB": value}, clear=True),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    bounded_runner.rss_limit_kb()
                self.assertEqual(raised.exception.code, expected_status)

    def test_process_snapshot_counts_group_and_descendants_once(self) -> None:
        snapshot = """\
101 1 101 100 S
102 101 101 200 R
103 102 999 300 S
104 1 101 400 Z
105 1 999 500 S
"""
        with (
            patch.object(bounded_runner, "_child_pid", 101),
            patch.object(bounded_runner, "_child_pgid", 101),
            patch.object(
                bounded_runner,
                "read_bounded_process_snapshot",
                return_value=snapshot,
            ) as read_snapshot,
        ):
            self.assertEqual(bounded_runner.process_snapshot(), (1000, 2, True))
        read_snapshot.assert_called_once_with(
            ["-axo", "pid=,ppid=,pgid=,rss=,stat="],
            max_bytes=bounded_runner.MAX_PROCESS_SNAPSHOT_BYTES,
            max_rows=bounded_runner.MAX_PROCESS_ROWS,
            timeout_seconds=bounded_runner.PROCESS_SNAPSHOT_TIMEOUT_SECONDS,
            kill_wait_seconds=bounded_runner.PROCESS_SNAPSHOT_KILL_WAIT_SECONDS,
            chunk_bytes=bounded_runner.PROCESS_SNAPSHOT_CHUNK_BYTES,
        )

    def test_process_snapshot_rejects_incomplete_rows(self) -> None:
        with (
            patch.object(bounded_runner, "_child_pid", 101),
            patch.object(bounded_runner, "_child_pgid", 101),
            patch.object(
                bounded_runner,
                "read_bounded_process_snapshot",
                return_value="101 1 101 100 S\nmalformed\n",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid row"):
                bounded_runner.process_snapshot()

    def test_process_snapshot_rejects_duplicate_process_ids(self) -> None:
        snapshot = "101 1 101 524288 S\n101 1 101 0 S\n"
        with (
            patch.object(bounded_runner, "_child_pid", 101),
            patch.object(bounded_runner, "_child_pgid", 101),
            patch.object(bounded_runner, "read_bounded_process_snapshot", return_value=snapshot),
        ):
            with self.assertRaisesRegex(RuntimeError, "duplicate process id"):
                bounded_runner.process_snapshot()

    def test_process_snapshot_rejects_an_empty_successful_table(self) -> None:
        with patch.object(bounded_runner, "read_bounded_process_snapshot", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "process snapshot was empty"):
                bounded_runner.process_snapshot()

    def test_missing_live_root_does_not_block_wait(self) -> None:
        child = SimpleNamespace(poll=lambda: None, wait=lambda: self.fail("blocking wait"))
        with self.assertRaisesRegex(RuntimeError, "omitted a root that is still running"):
            bounded_runner.child_status_after_snapshot(child, root_live=False)

    def test_stop_group_returns_after_terminated_members_exit(self) -> None:
        with (
            patch.object(bounded_runner, "_child_pgid", 812),
            patch.object(
                bounded_runner,
                "process_snapshot",
                side_effect=((0, 1, True), (0, 0, False)),
            ),
            patch.object(bounded_runner.os, "killpg") as killpg,
            patch.object(bounded_runner.time, "sleep"),
        ):
            bounded_runner.stop_group()
        killpg.assert_called_once_with(812, signal.SIGTERM)

    def test_stop_group_escalates_when_grace_period_expires(self) -> None:
        with (
            patch.object(bounded_runner, "_child_pgid", 913),
            patch.object(bounded_runner.time, "monotonic", side_effect=(0.0, 3.0)),
            patch.object(bounded_runner, "process_snapshot") as snapshot,
            patch.object(bounded_runner.os, "killpg") as killpg,
            patch.object(bounded_runner.time, "sleep"),
        ):
            bounded_runner.stop_group()
        snapshot.assert_not_called()
        self.assertEqual(
            killpg.call_args_list,
            [call(913, signal.SIGTERM), call(913, signal.SIGKILL)],
        )

    def test_entry_point_refuses_to_launch_without_reauthorization(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(sys, "argv", ["run_bounded_stage1_command.py", "/bin/true"]),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            bounded_runner.main()
        self.assertEqual(raised.exception.code, 125)

    def test_signal_exit_status_is_normalized(self) -> None:
        self.assertEqual(bounded_runner.normalized_status(42), 42)
        self.assertEqual(bounded_runner.normalized_status(-9), 137)

    def test_opt_in_launcher_and_script_must_be_paired(self) -> None:
        args = SimpleNamespace(export_scan_launcher="/bin/elisac")
        with self.assertRaisesRegex(WasmBuildError, "must be supplied together"):
            load_export_scan(Path("/tmp/input.elisa"), args)

