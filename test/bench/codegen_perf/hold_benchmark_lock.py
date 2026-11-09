import fcntl
import os
import sys
import time

fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("busy", flush=True)
    raise SystemExit(3)
print("locked", flush=True)
parent_pid = int(sys.argv[2])
while os.getppid() == parent_pid:
    time.sleep(0.5)
