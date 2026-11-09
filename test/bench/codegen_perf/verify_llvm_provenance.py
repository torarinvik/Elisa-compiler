import json
import shlex
import subprocess
import sys
from pathlib import Path

manifest_path, llvm_config, linked_library, static_count, *static_args = sys.argv[1:]
toolchain = json.loads(Path(manifest_path).read_text()).get("llvm_toolchain")
if not isinstance(toolchain, dict):
    raise SystemExit("Stage1 provenance does not record its LLVM toolchain")
mode = toolchain.get("link_mode")
if linked_library == "static-archives":
    if mode != "static":
        raise SystemExit(f"Stage1 provenance says LLVM link mode is {mode!r}, but no shared LLVM library is linked")
    recorded = toolchain.get("static_archives")
    if not isinstance(recorded, list) or not recorded:
        raise SystemExit("Stage1 provenance does not record the static LLVM archives")
    actual_paths = {str(Path(path).resolve()) for path in static_args[:int(static_count)]}
    recorded_paths = {str(Path(item["path"]).resolve()) for item in recorded if isinstance(item, dict) and "path" in item}
    if not actual_paths or actual_paths != recorded_paths:
        raise SystemExit("Stage1 static LLVM archives do not match the archives selected by llvm-config")
else:
    if mode != "dynamic":
        raise SystemExit(f"Stage1 provenance says LLVM link mode is {mode!r}, but a shared LLVM library is linked")
    try:
        result = subprocess.run(
            [llvm_config, "--link-shared", "--libfiles"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"could not query selected shared LLVM library: {error}") from error
    selected = {
        str(Path(path).resolve())
        for path in shlex.split(result.stdout)
        if path.endswith((".dylib", ".so")) or ".so." in path
    }
    if len(selected) != 1:
        raise SystemExit(f"llvm-config did not identify exactly one shared LLVM library: {sorted(selected)}")
    linked = str(Path(linked_library).resolve())
    if linked not in selected:
        raise SystemExit(f"Stage1 links {linked}, but selected llvm-config resolves to {sorted(selected)}")
    libdir = Path(subprocess.run(
        [llvm_config, "--libdir"], capture_output=True, text=True, check=True
    ).stdout.strip()).resolve()
    if Path(linked).parent != libdir:
        raise SystemExit(f"linked LLVM library {linked} is outside selected LLVM libdir {libdir}")
    recorded_libraries = toolchain.get("dynamic_libraries")
    if not isinstance(recorded_libraries, list) or linked not in {
        str(Path(item["path"]).resolve()) for item in recorded_libraries
        if isinstance(item, dict) and "path" in item
    }:
        raise SystemExit("Stage1 provenance does not fingerprint its selected dynamic LLVM library")
