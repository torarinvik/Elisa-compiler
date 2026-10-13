"""Capture optional per-process retired-instruction counters for local benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
from typing import Sequence


TIME_PATH = Path("/usr/bin/time")
MACOS_TIME_METHOD = "macOS /usr/bin/time -l"


@dataclass(frozen=True)
class ProcessCounter:
    instructions_retired: int | None
    cycles_elapsed: int | None
    child_cpu_seconds: float | None
    status: str


def method_description() -> str:
    if os.uname().sysname != "Darwin":
        return "unavailable: retired-instruction counters require macOS /usr/bin/time -l"
    if not TIME_PATH.is_file() or not os.access(TIME_PATH, os.X_OK):
        return "unavailable: /usr/bin/time is missing or not executable"
    return MACOS_TIME_METHOD


METHOD_DESCRIPTION = method_description()


def counters_available() -> bool:
    return METHOD_DESCRIPTION == MACOS_TIME_METHOD


def new_report_path(directory: Path) -> Path | None:
    if not counters_available():
        return None
    fd, raw_path = tempfile.mkstemp(prefix=".retired-counter-", suffix=".txt", dir=directory)
    os.close(fd)
    path = Path(raw_path)
    path.unlink()
    return path


def wrap_command(command: Sequence[str], report_path: Path | None) -> list[str]:
    arguments = [str(argument) for argument in command]
    if report_path is None:
        return arguments
    return [str(TIME_PATH), "-l", "-o", str(report_path), *arguments]


def unavailable_counter() -> ProcessCounter:
    return ProcessCounter(None, None, None, "unavailable")


def read_report(report_path: Path | None) -> ProcessCounter:
    if report_path is None:
        return unavailable_counter()
    try:
        report = report_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return unavailable_counter()

    def integer_for(label: str) -> int | None:
        match = re.search(rf"^\s*([\d,]+)\s+{re.escape(label)}\s*$", report, re.MULTILINE)
        if match is None:
            return None
        return int(match.group(1).replace(",", ""))

    instruction_count = integer_for("instructions retired")
    cycle_count = integer_for("cycles elapsed")
    number = r"\d+(?::\d{2})*(?:\.\d+)?"
    cpu_match = re.search(
        rf"^\s*({number})\s+real\s+({number})\s+user\s+({number})\s+sys\s*$",
        report,
        re.MULTILINE,
    )

    def duration_seconds(value: str) -> float:
        parts = value.split(":")
        seconds = float(parts[-1])
        multiplier = 60
        for part in reversed(parts[:-1]):
            seconds += int(part) * multiplier
            multiplier *= 60
        return seconds

    cpu_seconds = None
    if cpu_match is not None:
        user_seconds = duration_seconds(cpu_match.group(2))
        system_seconds = duration_seconds(cpu_match.group(3))
        cpu_seconds = user_seconds + system_seconds

    status = "available" if instruction_count is not None and cycle_count is not None else "unavailable"
    if status == "unavailable":
        instruction_count = cycle_count = None
    return ProcessCounter(instruction_count, cycle_count, cpu_seconds, status)
