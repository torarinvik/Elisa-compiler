"""Collect and summarize paired semantic benchmark measurements."""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any


def paired_timing_summary(ratios: list[float], label: str) -> dict[str, Any]:
    if not ratios or any(not math.isfinite(ratio) or ratio <= 0 for ratio in ratios):
        raise RuntimeError(f"{label}: paired request timing produced an invalid graph-on/off ratio")
    return {
        "median_paired_graph_on_over_off_ratio": statistics.median(ratios),
        "geometric_mean_paired_graph_on_over_off_ratio": math.exp(
            sum(math.log(ratio) for ratio in ratios) / len(ratios)
        ),
        "paired_graph_on_wins": sum(ratio < 1.0 for ratio in ratios),
        "paired_graph_off_wins": sum(ratio > 1.0 for ratio in ratios),
        "paired_ties": sum(ratio == 1.0 for ratio in ratios),
        "paired_request_ratios": ratios,
    }

def paired_counter_summary(ratios: list[float], label: str) -> dict[str, Any]:
    if not ratios or any(not math.isfinite(ratio) or ratio <= 0 for ratio in ratios):
        raise RuntimeError(f"{label}: paired process-counter ratio is invalid")
    return {
        "median_paired_graph_on_over_off_ratio": statistics.median(ratios),
        "geometric_mean_paired_graph_on_over_off_ratio": math.exp(
            sum(math.log(ratio) for ratio in ratios) / len(ratios)
        ),
        "paired_graph_on_wins": sum(ratio < 1.0 for ratio in ratios),
        "paired_graph_off_wins": sum(ratio > 1.0 for ratio in ratios),
        "paired_ties": sum(ratio == 1.0 for ratio in ratios),
        "paired_request_ratios": ratios,
    }

class DarwinRusageInfoV4(ctypes.Structure):
    # sys/resource.h: the UUID is followed by 35 uint64 fields; instructions
    # and cycles are fields 30 and 31, respectively.
    _fields_ = [("uuid", ctypes.c_ubyte * 16), ("values", ctypes.c_uint64 * 35)]

class DarwinTimebaseInfo(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

def mach_ticks_to_ns(ticks: int, numer: int, denom: int) -> int:
    if ticks < 0 or numer <= 0 or denom <= 0:
        raise ValueError("invalid Mach timebase or tick count")
    return ticks * numer // denom

class DarwinProcessCounters:
    """Read cumulative retired instructions and cycles for one macOS PID."""

    INSTRUCTIONS_INDEX = 29
    CYCLES_INDEX = 30
    PHYSICAL_FOOTPRINT_INDEX = 7
    LIFETIME_MAX_FOOTPRINT_INDEX = 28

    def __init__(self) -> None:
        self.libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        self.proc_pid_rusage = self.libproc.proc_pid_rusage
        self.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        self.proc_pid_rusage.restype = ctypes.c_int
        self.libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        timebase = self.libsystem.mach_timebase_info
        timebase.argtypes = [ctypes.POINTER(DarwinTimebaseInfo)]
        timebase.restype = ctypes.c_int
        info = DarwinTimebaseInfo()
        if timebase(ctypes.byref(info)) != 0 or info.numer == 0 or info.denom == 0:
            raise RuntimeError("could not establish Mach CPU-time units")
        self.timebase_numer = int(info.numer)
        self.timebase_denom = int(info.denom)

    def snapshot_with_memory(self, pid: int) -> tuple[dict[str, int], dict[str, int]]:
        info = DarwinRusageInfoV4()
        buffer = ctypes.cast(ctypes.byref(info), ctypes.POINTER(ctypes.c_void_p))
        if self.proc_pid_rusage(pid, 4, buffer) != 0:
            error = ctypes.get_errno()
            raise OSError(error, f"proc_pid_rusage({pid}) failed")
        counters = {
            "instructions_retired": int(info.values[self.INSTRUCTIONS_INDEX]),
            "cycles_elapsed": int(info.values[self.CYCLES_INDEX]),
            "cpu_time_ns": mach_ticks_to_ns(
                int(info.values[0] + info.values[1]), self.timebase_numer, self.timebase_denom
            ),
        }
        memory = {
            "physical_footprint_bytes": int(info.values[self.PHYSICAL_FOOTPRINT_INDEX]),
            "lifetime_max_physical_footprint_bytes": int(info.values[self.LIFETIME_MAX_FOOTPRINT_INDEX]),
        }
        return counters, memory

    def snapshot(self, pid: int) -> dict[str, int]:
        counters, _ = self.snapshot_with_memory(pid)
        return counters

def memory_observation(before: dict[str, int], after: dict[str, int]) -> dict[str, Any]:
    """Footprint is a gauge: decreases are valid, unlike cumulative counters."""
    return {
        "before": dict(before),
        "after": dict(after),
        "physical_footprint_change_bytes": after["physical_footprint_bytes"] - before["physical_footprint_bytes"],
    }

def find_stage1_pid(launcher_pid: int, stage1: Path, timeout_seconds: float) -> int:
    """Find the guarded shell's direct Stage1 child, which owns compiler work."""
    deadline = time.monotonic() + min(timeout_seconds, 10.0)
    expected = stage1.resolve()
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    proc_pidpath = libproc.proc_pidpath
    proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    proc_pidpath.restype = ctypes.c_int
    while time.monotonic() < deadline:
        listing = subprocess.run(
            ["ps", "-axo", "pid=,ppid="],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        matches: list[int] = []
        for line in listing.splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            try:
                pid, parent = int(fields[0]), int(fields[1])
            except ValueError:
                continue
            if parent != launcher_pid:
                continue
            path_buffer = ctypes.create_string_buffer(4096)
            if proc_pidpath(pid, path_buffer, len(path_buffer)) <= 0:
                continue
            executable = Path(os.fsdecode(path_buffer.value))
            if executable.resolve() == expected:
                matches.append(pid)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RuntimeError(f"found multiple Stage1 children for launcher pid {launcher_pid}: {matches}")
        time.sleep(0.01)
    raise RuntimeError(f"could not find Stage1 child of launcher pid {launcher_pid}")

def counter_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    delta = {key: after[key] - before[key] for key in before}
    if any(value < 0 for value in delta.values()):
        raise RuntimeError("Stage1 process counters moved backwards")
    return delta

def paired_counter_measurements(
    arms: list[dict[str, Any]],
    pair_count: int,
    labels: tuple[str, ...] | list[str],
    field: str,
    description: str,
) -> dict[str, Any]:
    per_label: dict[str, Any] = {}
    aggregate_ratios: list[float] = []
    for label in labels:
        ratios: list[float] = []
        off_samples: list[int] = []
        on_samples: list[int] = []
        for pair_index in range(pair_count):
            off_arm = next(arm for arm in arms if arm["pair"] == pair_index and arm["mode"] == "graph-off")
            on_arm = next(arm for arm in arms if arm["pair"] == pair_index and arm["mode"] == "graph-on")
            off_value = next(request[field] for request in off_arm["requests"] if request["label"] == label)
            on_value = next(request[field] for request in on_arm["requests"] if request["label"] == label)
            if off_value <= 0 or on_value <= 0:
                raise RuntimeError(f"{description} {label}: process-counter sample must be positive")
            off_samples.append(off_value)
            on_samples.append(on_value)
            ratios.append(on_value / off_value)
        per_label[label] = {
            "graph_off_median": statistics.median(off_samples),
            "graph_on_median": statistics.median(on_samples),
            "graph_on_over_off_median_ratio": statistics.median(on_samples) / statistics.median(off_samples),
            "paired_samples": len(ratios),
            **paired_counter_summary(ratios, f"{description} {label}"),
        }
        aggregate_ratios.extend(ratios)
    return {
        "per_label": per_label,
        "paired_aggregate": paired_counter_summary(aggregate_ratios, description),
    }

def paired_mode_measurements(
    arms: list[dict[str, Any]],
    pair_count: int,
    labels: tuple[str, ...] | list[str],
    field: str,
    baseline_mode: str,
    treatment_mode: str,
    description: str,
) -> dict[str, Any]:
    """Compare one opt-in mode with a baseline without changing legacy summaries."""
    per_label: dict[str, Any] = {}
    aggregate_ratios: list[float] = []
    for label in labels:
        ratios: list[float] = []
        baseline_samples: list[float] = []
        treatment_samples: list[float] = []
        for pair_index in range(pair_count):
            baseline_arm = next(
                arm for arm in arms if arm["pair"] == pair_index and arm["mode"] == baseline_mode
            )
            treatment_arm = next(
                arm for arm in arms if arm["pair"] == pair_index and arm["mode"] == treatment_mode
            )
            baseline_value = next(
                request[field] for request in baseline_arm["requests"] if request["label"] == label
            )
            treatment_value = next(
                request[field] for request in treatment_arm["requests"] if request["label"] == label
            )
            if baseline_value <= 0 or treatment_value <= 0:
                raise RuntimeError(f"{description} {label}: paired measurement must be positive")
            baseline_samples.append(baseline_value)
            treatment_samples.append(treatment_value)
            ratio = treatment_value / baseline_value
            if not math.isfinite(ratio) or ratio <= 0:
                raise RuntimeError(f"{description} {label}: paired ratio is invalid")
            ratios.append(ratio)
        per_label[label] = {
            f"{baseline_mode}_median": statistics.median(baseline_samples),
            f"{treatment_mode}_median": statistics.median(treatment_samples),
            "median_treatment_over_baseline_ratio": statistics.median(ratios),
            "paired_ratios": ratios,
        }
        aggregate_ratios.extend(ratios)
    if not aggregate_ratios or any(not math.isfinite(ratio) for ratio in aggregate_ratios):
        raise RuntimeError(f"{description}: paired comparison produced an invalid ratio")
    aggregate = {
        "median_treatment_over_baseline_ratio": statistics.median(aggregate_ratios),
        "geometric_mean_treatment_over_baseline_ratio": math.exp(
            sum(math.log(ratio) for ratio in aggregate_ratios) / len(aggregate_ratios)
        ),
        "treatment_wins": sum(ratio < 1.0 for ratio in aggregate_ratios),
        "baseline_wins": sum(ratio > 1.0 for ratio in aggregate_ratios),
        "ties": sum(ratio == 1.0 for ratio in aggregate_ratios),
        "paired_samples": len(aggregate_ratios),
    }
    return {
        "baseline_mode": baseline_mode,
        "treatment_mode": treatment_mode,
        "per_label": per_label,
        "paired_aggregate": aggregate,
    }
