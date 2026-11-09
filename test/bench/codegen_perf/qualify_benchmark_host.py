import json
import hashlib
import os
import platform
import re
import sys
from pathlib import Path

output = Path(sys.argv[1])
system = sys.argv[2]
result = {
    "system": system,
    "machine": platform.machine(),
    "qualified": False,
    "allowed_cpu_count": None,
    "allowed_cpu_ids": None,
    "effective_cgroup_cpu_quota": None,
    "cgroup_quota_sources": [],
    "cgroup_membership_lines": [],
    "cgroup_mountinfo_sha256": None,
    "cgroup_namespace": None,
    "reason": "Mac timing is exploratory; the project qualification target is a 64-core x86_64 Linux host",
}

def unescape_mount(value):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)

def mapped_cgroup_dir(cgroup_path, mount_root, mount_point):
    cgroup_path = Path(cgroup_path)
    mount_root = Path(mount_root)
    try:
        relative = cgroup_path.relative_to(mount_root)
    except ValueError:
        return None
    return Path(mount_point) / relative

if system == "Linux":
    issues = []
    try:
        allowed_cpu_ids = sorted(os.sched_getaffinity(0))
        allowed = len(allowed_cpu_ids)
    except (AttributeError, OSError):
        allowed_cpu_ids = None
        allowed = os.cpu_count() or 0
        issues.append("could not read the process CPU affinity mask")
    result["allowed_cpu_count"] = allowed
    result["allowed_cpu_ids"] = allowed_cpu_ids

    memberships = []
    try:
        membership_lines = Path("/proc/self/cgroup").read_text().splitlines()
        result["cgroup_membership_lines"] = membership_lines
        for line in membership_lines:
            _, controllers, path = line.split(":", 2)
            if not controllers:
                memberships.append(("v2", path))
            elif "cpu" in controllers.split(","):
                memberships.append(("v1", path))
    except (OSError, ValueError) as error:
        issues.append(f"could not parse /proc/self/cgroup: {error}")

    mounts = []
    try:
        mountinfo_text = Path("/proc/self/mountinfo").read_text()
        result["cgroup_mountinfo_sha256"] = hashlib.sha256(mountinfo_text.encode()).hexdigest()
        for line in mountinfo_text.splitlines():
            if " - " not in line:
                continue
            before, after = line.split(" - ", 1)
            before_fields = before.split()
            after_fields = after.split()
            if len(before_fields) < 5 or len(after_fields) < 3:
                continue
            fs_type = after_fields[0]
            options = set(after_fields[2].split(","))
            if fs_type == "cgroup2":
                mounts.append(("v2", unescape_mount(before_fields[3]), unescape_mount(before_fields[4])))
            elif fs_type == "cgroup" and "cpu" in options:
                mounts.append(("v1", unescape_mount(before_fields[3]), unescape_mount(before_fields[4])))
    except OSError as error:
        issues.append(f"could not read /proc/self/mountinfo: {error}")

    try:
        self_cgroup_ns = os.readlink("/proc/self/ns/cgroup")
        init_cgroup_ns = os.readlink("/proc/1/ns/cgroup")
        result["cgroup_namespace"] = {"self": self_cgroup_ns, "init": init_cgroup_ns}
        if self_cgroup_ns != init_cgroup_ns:
            issues.append("the process is in a separate cgroup namespace, so outer CPU quotas may be hidden")
    except OSError as error:
        issues.append(f"could not compare process and init cgroup namespaces: {error}")

    quotas = []
    for kind, cgroup_path in memberships:
        matched_mounts = [mount for mount in mounts if mount[0] == kind]
        if not matched_mounts:
            issues.append(f"no mounted {kind} CPU controller matches /proc/self/cgroup")
            continue
        values_found = False
        for _, mount_root, mount_point in matched_mounts:
            if Path(mount_root) != Path("/"):
                issues.append(f"{kind} CPU controller mount root {mount_root} hides possible outer quota ancestors")
            candidate = mapped_cgroup_dir(cgroup_path, mount_root, mount_point)
            if candidate is None or not candidate.exists():
                continue
            mount_path = Path(mount_point)
            current = candidate
            while True:
                quota_path = current / ("cpu.max" if kind == "v2" else "cpu.cfs_quota_us")
                period_path = current / "cpu.cfs_period_us"
                try:
                    if kind == "v2" and quota_path.is_file():
                        quota_text, period_text = quota_path.read_text().split()[:2]
                        values_found = True
                        if quota_text != "max":
                            quota, period = int(quota_text), int(period_text)
                            if period <= 0:
                                issues.append(f"invalid cgroup v2 CPU period at {quota_path}")
                            else:
                                cpus = quota / period
                                quotas.append(cpus)
                                result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "quota": quota, "period": period, "cpus": cpus})
                        else:
                            result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "quota": "max", "period": int(period_text), "cpus": None})
                    elif kind == "v1" and quota_path.is_file() and period_path.is_file():
                        quota = int(quota_path.read_text().strip())
                        period = int(period_path.read_text().strip())
                        values_found = True
                        if quota >= 0:
                            if period <= 0:
                                issues.append(f"invalid cgroup v1 CPU period at {period_path}")
                            else:
                                cpus = quota / period
                                quotas.append(cpus)
                                result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "period_path": str(period_path), "quota": quota, "period": period, "cpus": cpus})
                        else:
                            result["cgroup_quota_sources"].append({"quota_path": str(quota_path), "period_path": str(period_path), "quota": quota, "period": period, "cpus": None})
                except (OSError, ValueError, IndexError) as error:
                    issues.append(f"could not read CPU quota at {quota_path}: {error}")
                if current == mount_path or mount_path not in current.parents:
                    break
                current = current.parent
        if not values_found:
            issues.append(f"no readable CPU quota files found for {kind} cgroup {cgroup_path}")

    if not memberships:
        issues.append("/proc/self/cgroup exposes no v1 CPU or v2 membership")
    quota = min(quotas) if quotas else None
    result["effective_cgroup_cpu_quota"] = quota
    if platform.machine() != "x86_64":
        issues.append("the qualified host architecture is x86_64")
    if allowed < 64:
        issues.append(f"only {allowed} CPUs are allowed by affinity; at least 64 are required")
    if quota is not None and quota < 64:
        issues.append(f"effective cgroup CPU quota is {quota:.2f}; at least 64 are required")
    result["qualified"] = not issues
    result["reason"] = "; ".join(issues) if issues else "64 or more CPUs are available and no cgroup quota is below 64"

output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
if system == "Linux" and not result["qualified"]:
    print(f"Linux host is not eligible for a qualified comparison: {result['reason']}", file=sys.stderr)
    raise SystemExit(2)
