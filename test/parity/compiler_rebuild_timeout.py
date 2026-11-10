#!/usr/bin/env python3
"""Run a compiler rebuild with a strict 5-second process-group deadline."""
import os
import signal
import subprocess
import sys
import threading

for name in ("LIBRARY_PATH", "SDKROOT"):
    present = os.environ.pop(f"ELISA_REBUILD_{name}_SET")
    value = os.environ.pop(f"ELISA_REBUILD_{name}_VALUE")
    if present:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)

profile_enabled = os.environ.pop("ELISA_REBUILD_PROFILE", "") == "1"
child = subprocess.Popen(sys.argv[1:], start_new_session=True)
profile = f"/tmp/elisa-rebuild-profile-{child.pid}.txt"

def sample_rebuild():
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
            # Stage0 is built by Go. Sample the tool doing the work, not the
            # go command waiting for its worker to finish.
            workers = [pid for pid in descendants
                       if os.path.basename(processes.get(pid, (0, ""))[1]) in {"compile", "cgo", "link"}]
            if not workers:
                return
            target = min(workers)
        subprocess.run(["/usr/bin/sample", str(target), "1", "10", "-file", profile],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

sampler = None
if profile_enabled:
    sampler = threading.Timer(2, sample_rebuild)
    sampler.daemon = True
    sampler.start()

def terminate(signum, _frame):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()
    raise SystemExit(128 + signum)

signal.signal(signal.SIGTERM, terminate)
signal.signal(signal.SIGINT, terminate)
try:
    status = child.wait(timeout=5)
except subprocess.TimeoutExpired:
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()
    message = "compiler rebuild exceeded 5 seconds"
    if profile_enabled and os.path.isfile(profile):
        message += f"; sample: {profile}"
    print(message, file=sys.stderr)
    raise SystemExit(124)
finally:
    if sampler is not None:
        sampler.cancel()
raise SystemExit(status if status >= 0 else 128 - status)
