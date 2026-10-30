#!/usr/bin/env python3
"""Verify the benchmark preflight protects the effective compiler profile."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest


class CompilerEnvironmentTests(unittest.TestCase):
    def test_inherited_driver_override_cannot_replace_o3(self):
        script = Path(__file__).with_name("cross_language.sh").read_text()
        # Execute the real preflight, stopping before toolchain discovery/builds.
        preflight, marker, _ = script.partition("# Compare the ordinary native compiler path.")
        self.assertTrue(marker, "benchmark preflight boundary moved")
        clang = os.environ.get("ELISA_TEST_CLANG") or shutil.which("clang")
        bash = os.environ.get("ELISA_TEST_BASH") or shutil.which("bash")
        timeout = shutil.which("gtimeout") or shutil.which("timeout")
        self.assertTrue(clang and bash and timeout, "clang, bash and an external timeout are required")
        environment = os.environ.copy()
        environment["CCC_OVERRIDE_OPTIONS"] = "O0"
        environment["LD"] = "benchmark-selected-linker"
        # Establish that this driver honors the override: otherwise this would
        # not test the failure mode the preflight must prevent.
        driver = [timeout, "-k", "0.1s", "29.7s", clang, "-###", "-O3", "-x", "c", "-c", os.devnull]
        contaminated = subprocess.run(driver, env=environment, capture_output=True, text=True, check=True)
        self.assertIn('"-O0"', contaminated.stderr)
        code = preflight + '\n' + r'''
[[ -z "${CCC_OVERRIDE_OPTIONS+x}" ]]
[[ "$LD" == benchmark-selected-linker ]]
found=0
for cleared in "${BENCH_ENV_OVERRIDES_CLEARED[@]}"; do
    [[ "$cleared" != CCC_OVERRIDE_OPTIONS ]] || found=1
done
[[ "$found" == 1 ]]
''' + "\nexec " + shlex.join(driver) + "\n"
        clean = subprocess.run([timeout, "-k", "0.1s", "29.7s", bash, "-c", code], env=environment, capture_output=True, text=True, check=True)
        self.assertIn('"-O3"', clean.stderr)
        self.assertNotIn('"-O0"', clean.stderr)


if __name__ == "__main__":
    unittest.main()
