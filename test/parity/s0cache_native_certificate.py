#!/usr/bin/env python3
"""Check real object-cache certificates against native tool replacement."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("compiler", type=Path)
args = parser.parse_args()
wrapper = Path(__file__).resolve().parents[2] / "tools/s0cache"
llc = shutil.which("llc")
if llc is None:
    llc = next((str(path) for path in (Path("/opt/homebrew/opt/llvm/bin/llc"),
                                      Path("/usr/local/opt/llvm/bin/llc"))
                if path.is_file()), None)
if llc is None or shutil.which("z3") is None:
    raise SystemExit("llc and z3 are required")
with tempfile.TemporaryDirectory(prefix="s0cache-native-cert-") as temp:
    root = Path(temp)
    bindir = root / "bin"
    bindir.mkdir()
    fake_llc = bindir / "llc"
    fake_llc.write_text('#!/bin/sh\nexec "$TEST_REAL_LLC" "$@"\n')
    fake_llc.chmod(0o755)
    source = root / "main.elisa"
    source.write_text("def main() -> i64:\n    return 42\n")
    env = os.environ.copy()
    env.update(ELISA_S0_REAL=str(args.compiler.resolve()),
               ELISA_S0_CACHE_DIR=str(root / "outer"),
               ELISA_S0_CACHE_STATS=str(root / "stats"),
               ELISAC_BUILD_CACHE_DIR=str(root / "core"),
               ELISA_LD="",
               ELISA_LLC="",
               ELISACORE_CODEGEN_JOBS="1",
               TEST_REAL_LLC=llc,
               PATH=os.pathsep.join((str(bindir), "/usr/bin", "/bin", os.environ["PATH"])))
    env.pop("ELISACORE_RETAINED_SERVER", None)
    env.pop("ELISACORE_CACHE_CERTIFICATE", None)

    def run():
        return subprocess.run([str(wrapper), "-emit", "obj", "-o",
                               str(root / "main.o"), str(source)],
                              env=env, capture_output=True, timeout=10, check=False)

    # A shell-script tool selector is not a complete certificate dependency.
    # Recompute until the real native llc is selected below.
    assert run().returncode == 0
    original = (root / "main.o").read_bytes()
    assert run().returncode == 0
    assert (root / "main.o").read_bytes() == original
    # Change the executable at the same path while preserving its behavior.
    fake_llc.write_text('#!/bin/sh\n# replacement\nexec "$TEST_REAL_LLC" "$@"\n')
    assert run().returncode == 0
    assert (root / "stats").read_text().splitlines() == [
        "miss\tobj\t-", "miss\tobj\t-", "miss\tobj\t-"
    ]
    # Explicit linker commands can be launchers or reference untracked script,
    # plugin, and response files. The outer cache must fail closed for overrides.
    linker = bindir / "custom-ld"
    linker.write_text("#!/bin/sh\nexit 0\n")
    linker.chmod(0o755)
    source.write_text("def main() -> i64:\n    return 43\n")
    env.update(ELISACORE_NATIVE_FRAGMENTS="1", ELISACORE_PARTITION_CACHE="1",
               ELISACORE_BUILD_CACHE="1", ELISA_LD=str(linker))
    assert run().returncode == 0
    assert run().returncode == 0
    linker.write_text("#!/bin/sh\n# replacement\nexit 0\n")
    assert run().returncode == 0
    assert (root / "stats").read_text().splitlines()[-3:] == [
        "bypass\tobj\telisa-ld-override",
        "bypass\tobj\telisa-ld-override",
        "bypass\tobj\telisa-ld-override",
    ]
    # Exercise the system selector (including xcrun on macOS) as well.
    fake_llc.unlink()
    env.pop("ELISA_LD")
    source.write_text("def main() -> i64:\n    return 44\n")
    assert run().returncode == 0
    assert run().returncode == 0
    assert (root / "stats").read_text().splitlines()[-2:] == [
        "miss\tobj\t-", "hit\tobj\t-"
    ]
print("native certificate invalidates a replaced compiler tool")
