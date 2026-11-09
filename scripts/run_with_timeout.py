#!/usr/bin/env python3
"""Run one command in an owned process group with a wall-clock deadline."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
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
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    if _group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        # The direct child is reaped by the caller's process exit if an OS-level
        # uninterruptible wait prevents completion; descendants have still been signaled.
        pass


def run(command: list[str], timeout_seconds: float) -> int:
    if not command or not command[0]:
        print("run_with_timeout: missing command", file=sys.stderr)
        return 2
    if timeout_seconds <= 0:
        print("run_with_timeout: timeout must be positive", file=sys.stderr)
        return 2
    try:
        process = subprocess.Popen(command, start_new_session=True)
    except OSError as error:
        print(f"run_with_timeout: cannot start {command[0]!r}: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda received, _frame, child=process: _terminate_on_signal(child, received))
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_group(process)
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
