"""Run and observe incremental semantic benchmark sessions."""
from __future__ import annotations

import os
from pathlib import Path
import select
import signal
import subprocess
import time
from typing import Any

from session_measurements import DarwinProcessCounters, counter_delta, find_stage1_pid, memory_observation
from session_workload import digest_bytes, mode_environment, normalized_transcript, report_fields, timing_rows


class PipeLineReader:
    """Read bytes directly so select() and Python's text buffer cannot diverge."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        self.fd = proc.stdout.fileno()
        self.buffer = bytearray()

    def readline(self, deadline: float) -> str:
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline]).rstrip(b"\r")
                del self.buffer[: newline + 1]
                return line.decode("utf-8", errors="replace")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for semantic-session response")
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if not ready:
                raise TimeoutError("timed out waiting for semantic-session response")
            chunk = os.read(self.fd, 65536)
            if not chunk:
                raise RuntimeError("semantic-session closed its output before replying")
            self.buffer.extend(chunk)

def read_response(reader: PipeLineReader, deadline: float) -> tuple[str, list[str]]:
    lines: list[str] = []
    while True:
        value = reader.readline(deadline)
        if value in {"0", "1", "2"}:
            return value, lines
        lines.append(value)

def stop_process_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()

def run_arm(
    *,
    root: Path,
    stage1: Path,
    source: Path,
    source_versions: list[str],
    workload: str,
    output: Path,
    pair_index: int,
    mode: str,
    order: int,
    functions: int,
    edits: int,
    timeout_seconds: float,
    collect_cache_report: bool = True,
) -> dict[str, Any]:
    source.write_text(source_versions[0], encoding="utf-8")
    arm_kind = "routing" if collect_cache_report else "timing"
    mode_dir = output / f"pair-{pair_index:02d}-{workload}-{mode}-{arm_kind}"
    mode_dir.mkdir()
    command = ["bash", str(root / "scripts/elisac_stage1.sh"), "semantic-session", str(source)]
    env = os.environ.copy()
    for key in (
        "ELISA_STAGE1_INCREMENTAL_CACHE_DIR",
        "ELISA_STAGE1_INCREMENTAL_SHADOW",
        "ELISA_STAGE1_INCREMENTAL_SHADOW_REPORT",
        "ELISA_STAGE1_PERMISSIVE",
        "ELISA_SEMANTIC_SERIAL",
    ):
        env.pop(key, None)
    arm_environment = mode_environment(mode)
    env.update(
        {
            "ELISA_STAGE1_BIN": str(stage1),
            "ELISA_STAGE1_INCREMENTAL_CACHE_REPORT": "1" if collect_cache_report else "0",
            "ELISA_STAGE1_TIMINGS": "1",
            "ELISA_ALLOW_STALE_STAGE1": "0",
            **arm_environment,
        }
    )
    started = time.perf_counter_ns()
    proc = subprocess.Popen(
        command,
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        start_new_session=True,
    )
    try:
        compiler_pid = find_stage1_pid(proc.pid, stage1, timeout_seconds)
        process_counters = DarwinProcessCounters()
    except BaseException:
        stop_process_group(proc)
        raise
    counter_totals = {"instructions_retired": 0, "cycles_elapsed": 0, "cpu_time_ns": 0}
    reader = PipeLineReader(proc)
    results: list[dict[str, Any]] = []
    request_specs: list[tuple[str, str | None]] = [("prime", None), ("exact-repeat", None)]
    request_specs.extend((f"body-edit-{index + 1}", source_versions[index + 1]) for index in range(edits))
    request_specs.append(("declaration-surface-edit", source_versions[-2]))
    request_specs.append(("post-surface-body-edit", source_versions[-1]))
    transcript_log = mode_dir / "requests.log"
    try:
        assert proc.stdin is not None
        with transcript_log.open("w", encoding="utf-8") as raw_log:
            for request_index, (label, next_source) in enumerate(request_specs):
                if next_source is not None:
                    source.write_text(next_source, encoding="utf-8")
                counters_before, memory_before = process_counters.snapshot_with_memory(compiler_pid)
                before = time.perf_counter_ns()
                proc.stdin.write(b"check\n")
                proc.stdin.flush()
                status, lines = read_response(reader, time.monotonic() + timeout_seconds)
                request_wall_ms = (time.perf_counter_ns() - before) / 1_000_000
                counters_after, memory_after = process_counters.snapshot_with_memory(compiler_pid)
                request_counters = counter_delta(counters_before, counters_after)
                for key, value in request_counters.items():
                    counter_totals[key] += value
                raw_log.write(f"=== request={request_index} label={label} status={status} ===\n")
                raw_log.writelines(line + "\n" for line in lines)
                if status != "0":
                    raise RuntimeError(f"benchmark fixture check {label} was rejected with status {status}")
                fields = report_fields(lines) if collect_cache_report else {}
                if not collect_cache_report and any(line.startswith("incremental-ga-cache:") for line in lines):
                    raise RuntimeError("counter-disabled timing arm unexpectedly emitted a cache report")
                result = {
                    "request_index": request_index,
                    "label": label,
                    "status": int(status),
                    "request_wall_ms": request_wall_ms,
                    **request_counters,
                    "memory": memory_observation(memory_before, memory_after),
                    "timings": timing_rows(lines),
                    "cache": fields,
                    "diagnostic_sha256": digest_bytes("\n".join(normalized_transcript(lines)).encode()),
                    "diagnostics": normalized_transcript(lines),
                }
                results.append(result)
            proc.stdin.write(b"quit\n")
            proc.stdin.flush()
            proc.stdin.close()
        remaining = max(0.1, timeout_seconds)
        status = proc.wait(timeout=remaining)
        if status != 0:
            raise RuntimeError(f"semantic-session process exited with status {status}")
    except BaseException:
        stop_process_group(proc)
        raise
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "cache_report_enabled": collect_cache_report,
        "arm_kind": arm_kind,
        "pair": pair_index,
        "workload": workload,
        "mode": mode,
        "mode_environment": arm_environment,
        "order": order,
        "process_wall_ms": elapsed_ms,
        "process_counters": {
            "status": "ok",
            "method": "macOS proc_pid_rusage RUSAGE_INFO_V4",
            "cpu_time_unit": "nanoseconds converted from Mach absolute ticks",
            "mach_timebase_numer": process_counters.timebase_numer,
            "mach_timebase_denom": process_counters.timebase_denom,
            **counter_totals,
            "pid": compiler_pid,
            "scope": "exact Stage1 child process; per-request deltas cover each check response",
            "memory_scope": "point-in-time footprint gauges; lifetime peak covers the whole process, not an individual request",
        },
        "source_path": str(source),
        "initial_source_sha256": digest_bytes(source_versions[0].encode()),
        "request_count": len(results),
        "requests": results,
    }
