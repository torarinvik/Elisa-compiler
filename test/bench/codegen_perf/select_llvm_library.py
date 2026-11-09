import shutil
import subprocess
import sys

if sys.platform == "darwin":
    args = ["otool", "-L", sys.argv[1]]
elif sys.platform.startswith("linux"):
    args = ["ldd", sys.argv[1]]
else:
    args = []

if not args or not shutil.which(args[0]):
    print("unknown")
else:
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if "libLLVM" not in line:
                continue
            if "=>" in line:
                path = line.split("=>", 1)[1].strip()
                if path.startswith("/"):
                    print(path.split(" (", 1)[0])
                else:
                    print("unknown")
                break
            path = line.strip().split(" (compatibility version", 1)[0]
            if path.startswith("/"):
                print(path)
                break
            else:
                print("unknown")
                break
        else:
            print("static-or-not-listed")
    except (OSError, subprocess.CalledProcessError):
        print("unknown")
