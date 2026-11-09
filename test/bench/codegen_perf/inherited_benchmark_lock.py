import fcntl
import os
import sys

try:
    fd = int(sys.argv[1])
    held = os.fstat(fd)
    expected = os.stat(sys.argv[2])
except (OSError, ValueError) as error:
    raise SystemExit(f"invalid inherited benchmark lock: {error}")
if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
    raise SystemExit("inherited benchmark lock does not refer to the configured host lock")
probe_fd = os.open(sys.argv[2], os.O_RDWR)
try:
    try:
        fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        fcntl.flock(probe_fd, fcntl.LOCK_UN)
        raise SystemExit("the inherited benchmark lock has no active parent lease")
finally:
    os.close(probe_fd)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError as error:
    raise SystemExit(f"inherited benchmark lock is not held by this descriptor: {error}")
