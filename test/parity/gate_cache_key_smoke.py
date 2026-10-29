#!/usr/bin/env python3
"""Check parity result caching against environment and tool replacement."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RUN_ALL = ROOT / "test/parity/run_all.sh"
CACHE_DIR = ROOT / "build/.gate-cache"


def bounded(command: list[str]) -> list[str]:
    timeout = shutil.which("gtimeout")
    if timeout:
        return [timeout, "-k", "1s", "29s", *command]
    timeout = shutil.which("timeout")
    if timeout:
        return [timeout, "29s", *command]
    raise RuntimeError("gate cache smoke requires gtimeout or timeout")


def run_check(result_dir: Path, name: str, check: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        bounded(["bash", str(RUN_ALL), "--exec-one", str(result_dir), name, str(check)]),
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(f"run_all exited {result.returncode}: {result.stderr}")
    return result.stdout


def main() -> None:
    env = os.environ.copy()
    for name in ("ELISA_GATE_TOOLCHAIN_HASH", "ELISA_GATE_NO_CACHE", "ELISA_GATE_LOG_DIR"):
        env.pop(name, None)
    env.update(ELISA_GATE_TREE_HASH="fixed-test-tree", ELISA_GATE_BINS_HASH="fixed-test-binaries")

    with tempfile.TemporaryDirectory(prefix="elisa-gate-cache-smoke-") as temporary:
        temp = Path(temporary)
        result_dir = temp / "results"
        result_dir.mkdir()
        check = temp / "check.sh"
        check.write_text('#!/usr/bin/env bash\n"$Z3"\n')
        check.chmod(0o700)
        names = (f"gate_env_{os.getpid()}", f"gate_binary_{os.getpid()}")
        cache_files = [CACHE_DIR / name for name in names]
        try:
            first = run_check(result_dir, names[0], check, env | {"Z3": "/usr/bin/true"})
            repeated = run_check(result_dir, names[0], check, env | {"Z3": "/usr/bin/true"})
            changed_env = run_check(result_dir, names[0], check, env | {"Z3": "/usr/bin/false"})
            if "(cached)" in first or "(cached)" not in repeated:
                raise AssertionError("identical environment did not reuse the successful result")
            if "(cached)" in changed_env or "FAIL" not in changed_env:
                raise AssertionError("changing the selected solver environment reused a stale result")

            tool = temp / "selected-tool"
            tool.write_text("#!/usr/bin/env bash\nexit 0\n")
            tool.chmod(0o700)
            first_tool = run_check(result_dir, names[1], check, env | {"Z3": str(tool)})
            same_tool = run_check(result_dir, names[1], check, env | {"Z3": str(tool)})
            tool.write_text("#!/usr/bin/env bash\nexit 1\n")
            tool.chmod(0o700)
            replaced_tool = run_check(result_dir, names[1], check, env | {"Z3": str(tool)})
            if "(cached)" in first_tool or "(cached)" not in same_tool:
                raise AssertionError("identical selected tool did not reuse the successful result")
            if "(cached)" in replaced_tool or "FAIL" not in replaced_tool:
                raise AssertionError("in-place tool replacement reused a stale result")
        finally:
            for cache_file in cache_files:
                cache_file.unlink(missing_ok=True)

    print("gate_cache_key_smoke OK: unchanged inputs hit; environment and tool changes miss")


if __name__ == "__main__":
    main()
