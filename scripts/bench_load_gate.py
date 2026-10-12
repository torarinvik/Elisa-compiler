"""Shared load-admission checks for the cross-language benchmark harness."""

from __future__ import annotations

import json
import hashlib
import math
import os
import platform
import sys
from pathlib import Path
from typing import Sequence


LOAD_FRACTION = 0.20


class LoadGateError(RuntimeError):
    """Raised when load or CPU entitlement cannot satisfy the benchmark gate."""


def _live_linux_capacity(qualification: dict[str, object]) -> tuple[int, float | None, dict[str, object]]:
    """Revalidate the Linux CPU entitlement recorded by the initial host qualifier."""
    machine = qualification.get("machine")
    if machine != "x86_64" or platform.machine() != machine:
        raise LoadGateError(f"Linux benchmark host architecture changed or is unqualified: {machine!r}")

    try:
        allowed_cpu_ids = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError) as error:
        raise LoadGateError(f"could not read current Linux CPU affinity: {error}") from error
    allowed = len(allowed_cpu_ids)
    expected_allowed = qualification.get("allowed_cpu_count")
    expected_cpu_ids = qualification.get("allowed_cpu_ids")
    if (
        not isinstance(expected_allowed, int)
        or isinstance(expected_allowed, bool)
        or not isinstance(expected_cpu_ids, list)
        or any(not isinstance(cpu_id, int) or isinstance(cpu_id, bool) for cpu_id in expected_cpu_ids)
        or len(expected_cpu_ids) != expected_allowed
        or len(set(expected_cpu_ids)) != len(expected_cpu_ids)
    ):
        raise LoadGateError("Linux host qualification is missing a valid CPU affinity set")
    expected_cpu_ids = sorted(expected_cpu_ids)
    if allowed != expected_allowed or allowed_cpu_ids != expected_cpu_ids:
        raise LoadGateError(
            f"current Linux affinity set {allowed_cpu_ids!r} differs from qualified set {expected_cpu_ids!r}"
        )
    if allowed < 64:
        raise LoadGateError(f"current Linux affinity permits only {allowed} CPUs; at least 64 are required")

    try:
        membership_lines = Path("/proc/self/cgroup").read_text().splitlines()
        mountinfo = Path("/proc/self/mountinfo").read_bytes()
        self_namespace = os.readlink("/proc/self/ns/cgroup")
        init_namespace = os.readlink("/proc/1/ns/cgroup")
    except OSError as error:
        raise LoadGateError(f"could not revalidate current Linux cgroup identity: {error}") from error
    if membership_lines != qualification.get("cgroup_membership_lines"):
        raise LoadGateError("current Linux cgroup membership differs from host qualification")
    expected_mountinfo_hash = qualification.get("cgroup_mountinfo_sha256")
    actual_mountinfo_hash = hashlib.sha256(mountinfo).hexdigest()
    if not isinstance(expected_mountinfo_hash, str) or actual_mountinfo_hash != expected_mountinfo_hash:
        raise LoadGateError("current Linux cgroup mount layout differs from host qualification")
    expected_namespace = qualification.get("cgroup_namespace")
    if expected_namespace != {"self": self_namespace, "init": init_namespace}:
        raise LoadGateError("current Linux cgroup namespace differs from host qualification")
    if self_namespace != init_namespace:
        raise LoadGateError("Linux benchmark process is in a hidden cgroup namespace")

    sources = qualification.get("cgroup_quota_sources")
    if not isinstance(sources, list) or not sources:
        raise LoadGateError("Linux host qualification has no cgroup quota provenance")
    quotas: list[float] = []
    verified_sources: list[dict[str, object]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise LoadGateError(f"Linux cgroup quota source {index} is malformed")
        quota_path_value = source.get("quota_path")
        if not isinstance(quota_path_value, str) or not quota_path_value:
            raise LoadGateError(f"Linux cgroup quota source {index} has no quota path")
        quota_path = Path(quota_path_value)
        try:
            if "period_path" in source:
                quota: int | str = int(quota_path.read_text().strip())
                period = int(Path(str(source["period_path"])).read_text().strip())
            else:
                quota_text, period_text = quota_path.read_text().split()[:2]
                quota = quota_text if quota_text == "max" else int(quota_text)
                period = int(period_text)
        except (OSError, ValueError, IndexError, TypeError) as error:
            raise LoadGateError(f"could not re-read Linux CPU quota at {quota_path}: {error}") from error
        if isinstance(source.get("quota"), bool) or quota != source.get("quota"):
            raise LoadGateError(f"Linux CPU quota changed since qualification: {quota_path}")
        if isinstance(source.get("period"), bool) or period != source.get("period") or period <= 0:
            raise LoadGateError(f"Linux CPU quota period changed or became invalid: {quota_path}")
        cpus = None if quota == "max" or (isinstance(quota, int) and quota < 0) else float(quota) / period
        expected_cpus = source.get("cpus")
        if cpus is None:
            if expected_cpus is not None:
                raise LoadGateError(f"Linux CPU quota capacity provenance changed: {quota_path}")
        elif (
            isinstance(expected_cpus, bool)
            or not isinstance(expected_cpus, (int, float))
            or not math.isfinite(float(expected_cpus))
            or abs(cpus - float(expected_cpus)) > 1e-12
        ):
            raise LoadGateError(f"Linux CPU quota capacity provenance changed: {quota_path}")
        if cpus is not None:
            quotas.append(cpus)
        verified_sources.append({"quota_path": quota_path_value, "quota": quota, "period": period, "cpus": cpus})

    effective_quota = min(quotas) if quotas else None
    expected_quota = qualification.get("effective_cgroup_cpu_quota")
    if effective_quota is None:
        if expected_quota is not None:
            raise LoadGateError("Linux effective CPU quota differs from host qualification")
    elif (
        isinstance(expected_quota, bool)
        or not isinstance(expected_quota, (int, float))
        or not math.isfinite(float(expected_quota))
        or abs(effective_quota - float(expected_quota)) > 1e-12
    ):
        raise LoadGateError("Linux effective CPU quota differs from host qualification")
    if effective_quota is not None and effective_quota < 64:
        raise LoadGateError(f"current Linux cgroup quota permits {effective_quota:.2f} CPUs; at least 64 are required")

    details: dict[str, object] = {
        "live_allowed_cpu_count": allowed,
        "live_allowed_cpu_ids": allowed_cpu_ids,
        "live_cgroup_cpu_quota": effective_quota,
        "live_cgroup_quota_sources": verified_sources,
        "live_cgroup_membership_lines": membership_lines,
        "live_cgroup_mountinfo_sha256": actual_mountinfo_hash,
        "live_cgroup_namespace": {"self": self_namespace, "init": init_namespace},
    }
    return allowed, effective_quota, details


def load_average() -> tuple[float | None, float | None, float | None]:
    try:
        values = os.getloadavg()
    except (AttributeError, OSError):
        return (None, None, None)
    return tuple(float(value) for value in values)


def effective_cpu_capacity(
    system: str,
    qualification_path: Path,
    *,
    require_live_linux: bool = False,
) -> tuple[float | None, dict[str, object]]:
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

    if require_live_linux:
        allowed, quota_value, live_details = _live_linux_capacity(qualification)
        details.update(live_details)
        details["allowed_cpu_count"] = allowed
        details["cgroup_cpu_quota"] = quota_value
        candidates = [float(allowed)]
        if quota_value is not None:
            candidates.append(quota_value)
        return min(candidates), details

    allowed = qualification.get("allowed_cpu_count")
    if not isinstance(allowed, int) or isinstance(allowed, bool) or allowed <= 0:
        raise LoadGateError(f"Linux host qualification has an invalid affinity CPU count: {allowed!r}")
    if allowed < 64:
        raise LoadGateError(f"Linux host qualification permits only {allowed} affinity CPUs; at least 64 are required")
    details["allowed_cpu_count"] = allowed
    candidates = [float(allowed)]

    quota = qualification.get("effective_cgroup_cpu_quota")
    if quota is not None:
        if isinstance(quota, bool) or not isinstance(quota, (int, float)):
            raise LoadGateError(f"Linux host qualification has an invalid cgroup CPU quota: {quota!r}")
        quota_value = float(quota)
        if not math.isfinite(quota_value) or quota_value <= 0:
            raise LoadGateError(f"Linux host qualification has an invalid cgroup CPU quota: {quota!r}")
        if quota_value < 64:
            raise LoadGateError(f"Linux host qualification permits only {quota_value:.2f} cgroup CPUs; at least 64 are required")
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
    require_live_linux: bool = False,
) -> dict[str, object]:
    capacity: float | None = None
    details: dict[str, object] = {"system": system}
    capacity_error: str | None = None
    try:
        capacity, details = effective_cpu_capacity(
            system, qualification_path, require_live_linux=require_live_linux,
        )
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
    if len(arguments) not in (4, 5) or arguments[0] != "preflight" or (len(arguments) == 5 and arguments[4] != "--require-live"):
        print("usage: bench_load_gate.py preflight OUTPUT HOST_QUALIFICATION SYSTEM [--require-live]", file=sys.stderr)
        return 2
    _, output, qualification, system = arguments[:4]
    require_live_linux = len(arguments) == 5
    try:
        check_load_gate(
            load_average(),
            "before benchmark preflight builds",
            Path(output),
            system,
            Path(qualification),
            preflight=True,
            require_live_linux=require_live_linux,
        )
    except LoadGateError as error:
        print(f"timing load gate failed before benchmark preflight: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
