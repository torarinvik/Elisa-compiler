"""Shared load-admission checks for the cross-language benchmark harness."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Sequence


LOAD_FRACTION = 0.20


class LoadGateError(RuntimeError):
    """Raised when load or CPU entitlement cannot satisfy the benchmark gate."""


def load_average() -> tuple[float | None, float | None, float | None]:
    try:
        values = os.getloadavg()
    except (AttributeError, OSError):
        return (None, None, None)
    return tuple(float(value) for value in values)


def effective_cpu_capacity(system: str, qualification_path: Path) -> tuple[float | None, dict[str, object]]:
    key = system.lower()
    logical = os.cpu_count()
    details: dict[str, object] = {
        "system": system,
        "logical_cpu_count": logical,
        "allowed_cpu_count": None,
        "cgroup_cpu_quota": None,
    }

    if key == "darwin":
        capacity = float(logical) if logical and logical > 0 else None
        return capacity, details
    if key != "linux":
        return None, details

    try:
        qualification = json.loads(qualification_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise LoadGateError(f"could not read Linux host qualification {qualification_path}: {error}") from error
    if not isinstance(qualification, dict):
        raise LoadGateError(f"Linux host qualification is not a JSON object: {qualification_path}")
    qualification_system = qualification.get("system")
    if not isinstance(qualification_system, str) or qualification_system.lower() != "linux" or qualification.get("qualified") is not True:
        raise LoadGateError(f"Linux host qualification is missing or failed: {qualification_path}")

    allowed = qualification.get("allowed_cpu_count")
    if not isinstance(allowed, int) or isinstance(allowed, bool) or allowed <= 0:
        raise LoadGateError(f"Linux host qualification has an invalid affinity CPU count: {allowed!r}")
    details["allowed_cpu_count"] = allowed
    candidates = [float(allowed)]

    quota = qualification.get("effective_cgroup_cpu_quota")
    if quota is not None:
        if isinstance(quota, bool) or not isinstance(quota, (int, float)):
            raise LoadGateError(f"Linux host qualification has an invalid cgroup CPU quota: {quota!r}")
        quota_value = float(quota)
        if not math.isfinite(quota_value) or quota_value <= 0:
            raise LoadGateError(f"Linux host qualification has an invalid cgroup CPU quota: {quota!r}")
        details["cgroup_cpu_quota"] = quota_value
        candidates.append(quota_value)

    return min(candidates), details


def check_load_gate(
    load: Sequence[float | None],
    stage: str,
    output: Path,
    system: str,
    qualification_path: Path,
    *,
    preflight: bool = False,
) -> dict[str, object]:
    capacity: float | None = None
    details: dict[str, object] = {"system": system}
    capacity_error: str | None = None
    try:
        capacity, details = effective_cpu_capacity(system, qualification_path)
    except LoadGateError as error:
        capacity_error = str(error)

    load1 = load[0] if load else None
    limit = LOAD_FRACTION * capacity if capacity is not None else None
    passed = (
        capacity is not None
        and math.isfinite(capacity)
        and capacity > 0
        and load1 is not None
        and math.isfinite(float(load1))
        and limit is not None
        and float(load1) <= limit
    )
    record: dict[str, object] = {
        **details,
        "stage": stage,
        "load1": load1,
        "load5": load[1] if len(load) > 1 else None,
        "load15": load[2] if len(load) > 2 else None,
        "effective_cpu_capacity": capacity,
        "load1_limit": limit,
        "passed": passed,
    }
    if capacity_error is not None:
        record["capacity_error"] = capacity_error

    if preflight:
        (output / "preflight_load_admission.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n"
        )
    else:
        with (output / "load_gate_checks.jsonl").open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")

    if not passed:
        reason = capacity_error or (
            f"load1={load1!r}, effective_cpu_capacity={capacity!r}, "
            f"required load1 <= {limit:.2f}" if limit is not None else
            f"load1={load1!r}, effective_cpu_capacity={capacity!r}, required load1 <= unavailable"
        )
        output_label = "Mac" if system.lower() == "darwin" else "Linux"
        timing_note = "No benchmark builds or timed samples were started.\n" if preflight else (
            "Any partial outputs and measurements from this run are unusable. "
            "An in-flight sample was allowed to finish before the post-sample check.\n"
        )
        (output / "ABORTED.txt").write_text(
            f"ABORTED — {output_label} timing load gate failed {stage}.\n"
            f"{reason}\n"
            f"{timing_note}"
        )
        raise LoadGateError(reason)
    return record


def main(arguments: list[str]) -> int:
    if len(arguments) != 4 or arguments[0] != "preflight":
        print("usage: bench_load_gate.py preflight OUTPUT HOST_QUALIFICATION SYSTEM", file=sys.stderr)
        return 2
    _, output, qualification, system = arguments
    try:
        check_load_gate(
            load_average(),
            "before benchmark preflight builds",
            Path(output),
            system,
            Path(qualification),
            preflight=True,
        )
    except LoadGateError as error:
        print(f"timing load gate failed before benchmark preflight: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
