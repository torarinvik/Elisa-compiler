import sys
live, fresh = sys.argv[1], sys.argv[2]
times = {}
for path in (live, fresh):
    try:
        for line in open(path):
            if line.startswith("#") or "\t" not in line:
                continue
            a, b = line.rstrip("\n").split("\t", 1)
            name, secs = (a, b) if path == live else (b, a)
            if path == fresh and secs == "0" and name in times:
                continue
            times[name] = secs
    except OSError:
        pass
with open(live + ".tmp", "w") as out:
    for name in sorted(times):
        out.write(f"{name}\t{times[name]}\n")
import os
os.replace(live + ".tmp", live)
