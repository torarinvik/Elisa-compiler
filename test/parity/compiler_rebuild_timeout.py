#!/usr/bin/env python3
"""Run a compiler rebuild with a strict 3-second process-group deadline."""
import os
import subprocess
import sys
import threading
from functools import lru_cache
from pathlib import Path

from compiler_rebuild_profile import go_compiler_package

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
        rows = subprocess.check_output(["ps", "-ww", "-axo", "pid=,ppid=,command="], text=True).splitlines()
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
        compiler_names = {
            os.path.basename(path)
            for name in ("ELISACORE_BIN", "ELISA_STAGE1_BIN")
            if (path := os.environ.get(name))
        }

        @lru_cache(maxsize=None)
        def executable(pid):
            command = processes.get(pid, (0, ""))[1]
            # The command column is not shell-quoted. An executable path may
            # contain spaces, so splitting it loses the basename (e.g. the
            # normal checkout under "Coding Projects"). Ask ps for the
            # executable path itself when this could be an Elisa compiler.
            if "elisac" in command or any(name in command for name in compiler_names):
                try:
                    path = subprocess.check_output(
                        ["ps", "-p", str(pid), "-o", "comm="], text=True
                    ).strip()
                    if path:
                        return os.path.basename(path)
                except (OSError, subprocess.SubprocessError):
                    pass
            return os.path.basename(command.split(None, 1)[0]) if command else ""

        candidates = [pid for pid in descendants if "elisac" in executable(pid) or executable(pid) in compiler_names]
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
                command = executable(pid)
                if command in {"ld", "ld64.lld", "ld.lld", "dsymutil"}:
                    workers.append((0, pid))
                elif command in {"compile", "clang", "clang++"} or command.startswith("clang-"):
                    workers.append((1, pid))
                elif command in {"cgo", "link"}:
                    workers.append((2, pid))
                elif command == "go":
                    workers.append((3, pid))
            # Provenance discovery can still be running before Go starts.
            # Capture its driver when no compiler worker is visible.
            target = min(workers)[1] if workers else child.pid
        # Report only the Go package name, not the full command line: compiler
        # arguments may contain paths or other user-provided values.
        if executable(target) == "compile":
            package = go_compiler_package(processes[target][1])
            if package:
                print(f"compiler rebuild sampled Go package: {package}", file=sys.stderr)
        # Go can finish one package and start the next while sampling. Resolve
        # symbols up front so an exiting worker still leaves a usable call graph.
        result = subprocess.run(["/usr/bin/sample", str(target), "1", "10", "-mayDie", "-file", profile],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=4, check=False)
        if result.returncode != 0:
            print(f"compiler rebuild sampling failed for pid {target}: {result.stderr.strip() or result.returncode}", file=sys.stderr)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

profile_enabled = os.environ.pop("ELISA_REBUILD_PROFILE", "") == "1"
os.environ["ELISA_REBUILD_SUPERVISED"] = "1"
sampler = None
profile = None

def schedule_sample(child):
    global sampler, profile
    profile = f"/tmp/elisa-rebuild-profile-{child.pid}.txt"
    # Leave time for process discovery and sample output before the deadline.
    sampler = threading.Timer(1.3, sample_rebuild, args=(child, profile))
    sampler.daemon = True
    sampler.start()

try:
    status = run(sys.argv[1:], 3, on_start=schedule_sample if profile_enabled else None)
finally:
    if sampler is not None:
        sampler.cancel()
        sampler.join(timeout=4)
if status == 124 and profile is not None and os.path.isfile(profile):
    print(f"compiler rebuild sample: {profile}", file=sys.stderr)
raise SystemExit(status)
