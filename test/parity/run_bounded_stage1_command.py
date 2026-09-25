#!/usr/bin/env python3
"""Run one WAsm parity command under sampled process-tree resource limits.

This is reactive supervision, not an OS memory sandbox. It uses a fresh session
instead of a platform-specific ``setsid`` executable, so Darwin and Linux use
the same process-group containment behavior.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from typing import NoReturn


MAX_RSS_KB = 2 * 1024 * 1024
MAX_SECONDS = 300
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_PROCESS_ROWS = 16_384
POLL_SECONDS = 0.05
TERM_GRACE_SECONDS = 2.0


def fail(message: str, status: int = 125) -> NoReturn:
    print(f"run_bounded_stage1_command: {message}", file=sys.stderr)
    raise SystemExit(status)


def rss_limit_kb() -> int:
    raw = os.environ.get("ELISA_STAGE1_MAX_RSS_KB", "")
    if len(raw) > 7:
        fail("RSS limit may not exceed 2097152 KB", 2)
    if not raw.isascii() or not raw.isdecimal() or int(raw) <= 0:
        fail("an explicit positive ELISA_STAGE1_MAX_RSS_KB is required")
    value = int(raw)
    if value > MAX_RSS_KB:
        fail("RSS limit must be in 1..2097152 KB", 2)
    return value


def process_snapshot() -> tuple[int, int, bool]:
    """Return (RSS KiB, live group member count, root is live)."""
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pgid=,rss=,stat="],
            check=True,
            capture_output=True,
            text=True,
            encoding="ascii",
            errors="strict",
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise RuntimeError(f"unable to read process snapshot: {exc}") from exc

    parents: dict[int, int] = {}
    groups: dict[int, int] = {}
    rss_by_pid: dict[int, int] = {}
    states: dict[int, str] = {}
    children: dict[int, list[int]] = {}
    lines = result.stdout.splitlines()
    if len(lines) > MAX_PROCESS_ROWS:
        raise RuntimeError("process snapshot exceeded the 16384-row limit")
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 5 or any(not field.isascii() or not field.isdecimal() for field in fields[:4]):
            raise RuntimeError("process snapshot contained an invalid row")
        pid, ppid, pgid, rss = (int(field) for field in fields[:4])
        parents[pid] = ppid
        groups[pid] = pgid
        rss_by_pid[pid] = rss
        states[pid] = fields[4]
        children.setdefault(ppid, []).append(pid)

    root_pid = _child_pid
    process_group = _child_pgid
    selected: set[int] = {root_pid} if root_pid in parents else set()
    pending = [root_pid] if root_pid in parents else []
    while pending:
        for pid in children.get(pending.pop(), []):
            if pid not in selected:
                selected.add(pid)
                pending.append(pid)

    accounted = {
        pid for pid in parents if groups[pid] == process_group or pid in selected
    }
    total_rss = sum(rss_by_pid[pid] for pid in accounted)
    live_group = sum(
        1
        for pid in parents
        if groups[pid] == process_group and not states[pid].startswith("Z")
    )
    root_live = root_pid in parents and not states[root_pid].startswith("Z")
    return total_rss, live_group, root_live


_child_pid = 0
_child_pgid = 0


def stop_group() -> None:
    if not _child_pgid:
        return
    try:
        os.killpg(_child_pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        pass

    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            _, live_group, _ = process_snapshot()
        except RuntimeError:
            # If inspection fails, fail closed and escalate after the grace.
            live_group = 1
        if live_group == 0:
            return
        time.sleep(0.1)
    try:
        os.killpg(_child_pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        pass


def normalized_status(returncode: int) -> int:
    return 128 - returncode if returncode < 0 else returncode


def main() -> int:
    global _child_pid, _child_pgid

    if os.environ.get("ELISASCRIPT_VALIDATION_REAUTHORIZED") != "1":
        fail("validation is disabled")
    if len(sys.argv) < 2:
        print(
            "usage: run_bounded_stage1_command.py COMMAND [ARGUMENTS...]",
            file=sys.stderr,
        )
        return 2
    limit = rss_limit_kb()

    try:
        output = tempfile.TemporaryFile(mode="w+b")
    except OSError as exc:
        fail(f"unable to create bounded output capture: {exc}")

    child: subprocess.Popen[bytes] | None = None
    completed = False

    def on_signal(signum: int, _frame: object) -> None:
        if child is not None and not completed:
            stop_group()
            try:
                child.wait(timeout=TERM_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        raise SystemExit(128 + signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, on_signal)

    try:
        try:
            child = subprocess.Popen(
                sys.argv[1:],
                stdin=None,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            fail(f"unable to launch command: {exc}")

        _child_pid = child.pid
        # Popen(start_new_session=True) makes the child the leader of a new
        # session and process group, so its PID is its PGID without a racey
        # post-launch os.getpgid() query.
        _child_pgid = child.pid

        start = time.monotonic()
        failure = ""
        failure_status = 125
        child_status: int | None = None
        while True:
            try:
                current_rss, live_group, root_live = process_snapshot()
            except RuntimeError as exc:
                failure = str(exc)
                break

            if child_status is None and not root_live:
                child_status = child.wait()
            if current_rss > limit:
                failure = f"process-group RSS {current_rss} KB exceeded {limit} KB"
                break

            try:
                output_bytes = os.fstat(output.fileno()).st_size
            except OSError as exc:
                failure = f"unable to measure captured output: {exc}"
                break
            if output_bytes > MAX_OUTPUT_BYTES:
                failure = f"captured output exceeded {MAX_OUTPUT_BYTES} bytes"
                break

            if time.monotonic() - start >= MAX_SECONDS:
                failure = f"command exceeded {MAX_SECONDS} seconds"
                failure_status = 124
                break
            if child_status is not None and live_group == 0:
                completed = True
                break
            time.sleep(POLL_SECONDS)

        if failure:
            print(
                f"run_bounded_stage1_command: {failure}; terminating the isolated process group",
                file=sys.stderr,
            )
            stop_group()
            child.wait()
            child_status = failure_status

        output.seek(0)
        while True:
            chunk = output.read(1024 * 1024)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        return normalized_status(child_status if child_status is not None else 125)
    finally:
        if child is not None and not completed:
            stop_group()
            if child.poll() is None:
                try:
                    child.wait(timeout=TERM_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
        output.close()


if __name__ == "__main__":
    raise SystemExit(main())
