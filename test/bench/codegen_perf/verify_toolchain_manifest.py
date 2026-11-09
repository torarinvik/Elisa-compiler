import json
import sys
from pathlib import Path

provenance = json.loads(Path(sys.argv[1]).read_text())
toolchain = provenance.get("llvm_toolchain")
if not isinstance(toolchain, dict):
    raise SystemExit("Stage1 provenance does not contain an LLVM toolchain fingerprint")
current = {}
for line in Path(sys.argv[2]).read_text().splitlines():
    digest, separator, raw_path = line.partition("  ")
    if separator:
        current[str(Path(raw_path).resolve())] = digest
artifacts = [toolchain.get("llvm_config_artifact"), toolchain.get("clang_artifact")]
for key in ("dynamic_libraries", "static_archives"):
    artifacts.extend(toolchain.get(key) or [])
for artifact in artifacts:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        raise SystemExit("Stage1 provenance contains a malformed LLVM artifact fingerprint")
    path = str(Path(artifact["path"]).resolve())
    if current.get(path) != artifact.get("sha256"):
        raise SystemExit(f"Stage1 LLVM provenance hash does not match current toolchain input: {path}")
