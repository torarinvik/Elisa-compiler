"""Read one process-table snapshot under byte, row, and wall-time limits."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Sequence


PROCESS_TABLE_EXECUTABLE = "/bin/ps"


class BoundedProcessSnapshotError(RuntimeError):
    """The process-table probe failed or exceeded a configured bound."""


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            pass
        except OSError:
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def read_bounded_process_snapshot(
    arguments: Sequence[str],
    *,
    max_bytes: int,
    max_rows: int,
    timeout_seconds: float,
    kill_wait_seconds: float,
    chunk_bytes: int,
) -> str:
    """Capture ASCII process-table output without buffering an unbounded pipe."""
    if (
        not arguments
        or max_bytes <= 0
        or max_rows <= 0
        or timeout_seconds <= 0
        or kill_wait_seconds <= 0
        or chunk_bytes <= 0
    ):
        raise ValueError("process snapshot bounds and command must be positive")

    try:
        process = subprocess.Popen(
            [PROCESS_TABLE_EXECUTABLE, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"LC_ALL": "C"},
            start_new_session=(os.name == "posix"),
            bufsize=0,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise BoundedProcessSnapshotError("unable to start process snapshot") from error

    stdout = process.stdout
    selector: selectors.BaseSelector | None = None
    terminated = False
    snapshot = bytearray()
    row_count = 0
    deadline = time.monotonic() + timeout_seconds

    def abort(message: str) -> None:
        nonlocal terminated
        if not terminated:
            _kill_process_group(process)
            terminated = True
        raise BoundedProcessSnapshotError(message)

    try:
        if stdout is None:
            abort("process snapshot has no output pipe")
        selector = selectors.DefaultSelector()
        selector.register(stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                abort(f"process snapshot timed out after {timeout_seconds:g} seconds")
            if not selector.select(remaining):
                continue

            read_size = min(chunk_bytes, max_bytes + 1 - len(snapshot))
            chunk = os.read(stdout.fileno(), read_size)
            if not chunk:
                break
            if len(snapshot) + len(chunk) > max_bytes:
                abort(f"process snapshot exceeded the {max_bytes}-byte limit")
            row_count += chunk.count(b"\n")
            if row_count > max_rows:
                abort(f"process snapshot exceeded the {max_rows}-row limit")
            snapshot.extend(chunk)

        if snapshot and not snapshot.endswith(b"\n"):
            row_count += 1
            if row_count > max_rows:
                abort(f"process snapshot exceeded the {max_rows}-row limit")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            abort(f"process snapshot timed out after {timeout_seconds:g} seconds")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            abort(f"process snapshot timed out after {timeout_seconds:g} seconds")
        if returncode != 0:
            raise BoundedProcessSnapshotError("process snapshot exited unsuccessfully")
        try:
            return snapshot.decode("ascii")
        except UnicodeDecodeError as error:
            raise BoundedProcessSnapshotError("process snapshot was not ASCII") from error
    except BoundedProcessSnapshotError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if not terminated:
            _kill_process_group(process)
            terminated = True
        raise BoundedProcessSnapshotError("unable to read process snapshot") from error
    finally:
        if selector is not None:
            selector.close()
        if process.poll() is None:
            if not terminated:
                _kill_process_group(process)
            try:
                process.wait(timeout=kill_wait_seconds)
            except subprocess.TimeoutExpired as error:
                raise BoundedProcessSnapshotError("unable to reap process snapshot") from error
        if stdout is not None:
            stdout.close()
