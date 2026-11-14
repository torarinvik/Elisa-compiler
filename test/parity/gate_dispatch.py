import os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
for name in ("LIBRARY_PATH", "SDKROOT"):
    present = os.environ.pop(f"ELISA_GATE_DISPATCH_{name}_SET")
    value = os.environ.pop(f"ELISA_GATE_DISPATCH_{name}_VALUE")
    if present:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
rd, root, jobs = sys.argv[1], sys.argv[2], int(sys.argv[3])
blob = open(os.path.join(rd, "cmdlist"), "rb").read()
records = [r for r in blob.split(b"\0\0") if r.strip(b"\0")]
def run(rec):
    args = [a.decode() for a in rec.split(b"\0") if a != b""]
    if len(args) < 3:
        print("parity dispatcher: invalid check record", file=sys.stderr)
        return 1
    result = subprocess.run(
        ["bash", os.path.join(root, "test/parity/run_all.sh"), "--exec-one", *args]
    )
    if result.returncode:
        print(f"parity dispatcher: worker {args[1]!r} exited {result.returncode}", file=sys.stderr)
    return result.returncode


with ThreadPoolExecutor(max_workers=jobs) as ex:
    futures = [ex.submit(run, r) for r in records]
    for extra in ("serial_lane.sh", "oracle_lane.sh"):
        pth = os.path.join(rd, extra)
        if os.path.exists(pth):
            futures.append(ex.submit(
                lambda p=pth: subprocess.run(["bash", p]).returncode))
    statuses = [future.result() for future in futures]
sys.exit(1 if any(statuses) else 0)
