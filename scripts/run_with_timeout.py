#!/usr/bin/env python3
"""Run one command in an owned process group with a wall-clock deadline."""
from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import closing
from typing import NoReturn


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_group(process: subprocess.Popen[bytes], grace_seconds: float = 1.0) -> None:
    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    if _group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        # The direct child is reaped by the caller's process exit if an OS-level
        # uninterruptible wait prevents completion; descendants have still been signaled.
        pass


def _wait_for_exit(process: subprocess.Popen[bytes], deadline: float) -> int:
    # POSIX Popen.wait(timeout=...) polls with up to 50 ms between checks.
    # On macOS the exit notification can wake the supervisor immediately.
    if hasattr(select, "kqueue"):
        try:
            with closing(select.kqueue()) as queue:
                event = select.kevent(
                    process.pid, filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                    fflags=select.KQ_NOTE_EXIT,
                )
                if not queue.control([event], 1, max(0.0, deadline - time.monotonic())):
                    raise subprocess.TimeoutExpired(process.args, 0)
        except OSError:
            # The child may have exited before registration, or the OS may
            # deny the event subscription. The ordinary wait handles both.
            pass
    return process.wait(timeout=max(0.0, deadline - time.monotonic()))


def run(
    command: list[str],
    timeout_seconds: float,
    *,
    on_start: Callable[[subprocess.Popen[bytes]], None] | None = None,
) -> int:
    if not command or not command[0]:
        print("run_with_timeout: missing command", file=sys.stderr)
        return 2
    if timeout_seconds <= 0:
        print("run_with_timeout: timeout must be positive", file=sys.stderr)
        return 2
    deadline = time.monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(command, start_new_session=True)
    except OSError as error:
        print(f"run_with_timeout: cannot start {command[0]!r}: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda received, _frame, child=process: _terminate_on_signal(child, received))
    try:
        if on_start is not None:
            on_start(process)
        return_code = _wait_for_exit(process, deadline)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            # macOS can reject the group signal while the leader is exiting,
            # before waitpid reports it. Try the child directly, then bound
            # cleanup and check that no process group remains.
            try:
                process.kill()
            except (ProcessLookupError, PermissionError):
                pass
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
            if process.poll() is None or _group_exists(process.pid):
                print(
                    f"run_with_timeout: cannot terminate owned process group {process.pid}: {error}",
                    file=sys.stderr,
                )
                return 125
        process.wait()
        print(
            f"run_with_timeout: deadline exceeded ({timeout_seconds:g}s); "
            f"terminated owned process group {process.pid}",
            file=sys.stderr,
        )
        return 124
    except KeyboardInterrupt:
        _terminate_group(process)
        return 130
    except BaseException:
        _terminate_group(process)
        raise
    return return_code if return_code >= 0 else 128 - return_code


def _terminate_on_signal(process: subprocess.Popen[bytes], signum: int) -> NoReturn:
    _terminate_group(process)
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> int:
    for name in ("LIBRARY_PATH", "SDKROOT"):
        present = os.environ.pop(f"ELISA_TIMEOUT_{name}_SET", None)
        value = os.environ.pop(f"ELISA_TIMEOUT_{name}_VALUE", "")
        if present == "x":
            os.environ[name] = value
        elif present == "":
            os.environ.pop(name, None)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeout_seconds", type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("usage: run_with_timeout.py TIMEOUT_SECONDS -- COMMAND [ARG ...]", file=sys.stderr)
        return 2
    if arguments.timeout_seconds <= 0:
        print("run_with_timeout: timeout must be positive", file=sys.stderr)
        return 2
    return run(command, arguments.timeout_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
