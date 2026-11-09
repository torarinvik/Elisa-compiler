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
        return
    subprocess.run(["bash", os.path.join(root, "test/parity/run_all.sh"), "--exec-one"] + args,
                   stderr=subprocess.DEVNULL)
with ThreadPoolExecutor(max_workers=jobs) as ex:
    futures = [ex.submit(run, r) for r in records]
    for extra in ("serial_lane.sh", "oracle_lane.sh"):
        pth = os.path.join(rd, extra)
        if os.path.exists(pth):
            futures.append(ex.submit(
                lambda p=pth: subprocess.run(["bash", p], stderr=subprocess.DEVNULL)))
    for f in futures:
        f.result()
