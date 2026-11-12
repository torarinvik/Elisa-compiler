#!/usr/bin/env python3
"""Run a compiler rebuild with a strict 3-second process-group deadline."""
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from run_with_timeout import run

for name in ("LIBRARY_PATH", "SDKROOT"):
    present = os.environ.pop(f"ELISA_REBUILD_{name}_SET")
    value = os.environ.pop(f"ELISA_REBUILD_{name}_VALUE")
    if present:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)

def sample_rebuild(child, profile):
    """Capture the running compiler before a timeout makes it impossible to inspect."""
    if child.poll() is not None or not os.path.exists("/usr/bin/sample"):
        return
    try:
        rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,comm="], text=True).splitlines()
        processes = {}
        for row in rows:
            parts = row.strip().split(None, 2)
            if len(parts) == 3:
                processes[int(parts[0])] = (int(parts[1]), parts[2])
        descendants = {child.pid}
        while True:
            updated = descendants | {pid for pid, (parent, _) in processes.items() if parent in descendants}
            if updated == descendants:
                break
            descendants = updated
        candidates = [pid for pid in descendants if "elisac" in os.path.basename(processes.get(pid, (0, ""))[1])]
        if candidates:
            # Prefer the oldest compiler process, not an arbitrary short-lived worker.
            # Set iteration order is unspecified, and sampling an exiting worker can
            # produce an empty call graph exactly when the rebuild times out.
            candidate_set = set(candidates)
            roots = [pid for pid in candidates if processes[pid][0] not in candidate_set]
            target = min(roots or candidates)
        else:
            # Go builds Stage0 and Clang builds the Stage1 LLVM bridge.
            # Sample the worker while the driver waits for it.
            workers = []
            for pid in descendants:
                command = os.path.basename(processes.get(pid, (0, ""))[1])
                if command in {"ld", "ld64.lld", "ld.lld", "dsymutil"}:
                    workers.append((0, pid))
                elif command in {"compile", "clang", "clang++"} or command.startswith("clang-"):
                    workers.append((1, pid))
                elif command in {"cgo", "link"}:
                    workers.append((2, pid))
                elif command == "go":
                    workers.append((3, pid))
            if not workers:
                return
            _, target = min(workers)
        subprocess.run(["/usr/bin/sample", str(target), "1", "10", "-file", profile],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

profile_enabled = os.environ.pop("ELISA_REBUILD_PROFILE", "") == "1"
os.environ["ELISA_REBUILD_SUPERVISED"] = "1"
sampler = None
profile = None

def schedule_sample(child):
    global sampler, profile
    profile = f"/tmp/elisa-rebuild-profile-{child.pid}.txt"
    # Sample the work still active near the deadline, after short dependency
    # compiles have finished. The one-second sample ends before the 3s kill.
    sampler = threading.Timer(1.8, sample_rebuild, args=(child, profile))
    sampler.daemon = True
    sampler.start()

try:
    status = run(sys.argv[1:], 3, on_start=schedule_sample if profile_enabled else None)
finally:
    if sampler is not None:
        sampler.cancel()
if status == 124 and profile is not None and os.path.isfile(profile):
    print(f"compiler rebuild sample: {profile}", file=sys.stderr)
raise SystemExit(status)
