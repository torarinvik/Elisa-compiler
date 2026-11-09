import hashlib
import sys
from pathlib import Path

source_dir = Path(sys.argv[1])
repository_root = Path(sys.argv[2])
benches = sys.argv[3:]
sources = [source_dir / "cross_language.sh", source_dir / "process_counter.py"]
for bench in benches:
    for suffix in ("elisa", "c", "rs", "zig"):
        sources.append(source_dir / f"{bench}.{suffix}")
for directory in (repository_root / "src", repository_root / "elisacore_std", repository_root / "scripts"):
    for source in directory.rglob("*"):
        if source.is_file() and source.suffix in (".elisa", ".elisai", ".c", ".h", ".sh", ".py"):
            sources.append(source)

for source in sorted(set(sources)):
    relative = source.relative_to(repository_root)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    print(f"{digest}  {relative}")
