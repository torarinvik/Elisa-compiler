import hashlib
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
rows = []
for raw_path in sys.argv[2:]:
    path = Path(raw_path)
    if not path.is_file():
        raise SystemExit(f"toolchain input is missing: {path}")
    rows.append((hashlib.sha256(path.read_bytes()).hexdigest(), str(path)))
manifest.write_text("".join(f"{digest}  {path}\n" for digest, path in sorted(rows)))
