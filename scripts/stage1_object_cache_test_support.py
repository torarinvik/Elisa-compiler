#!/usr/bin/env python3
"""Cache admission must never publish partial, corrupt, or mismatched bytes."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import stage1_object_cache as cache


class CacheTestFixture(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.entry, self.source, self.output = (root / p for p in ("cache/key.o", "source.o", "output.o"))
        self.source.write_bytes(b"object payload" * 100)
        self.output.write_bytes(b"previous valid output")


    def cache_project(self, name="project"):
        root = self.source.parent / name
        (root / "bin").mkdir(parents=True)
        (root / "elisacore_std").mkdir()
        (root / "elisacore_std" / "runtime.elisa").write_text("# fixture\n")
        (root / "scripts").mkdir()
        scripts = Path(__file__).resolve().parent
        for name in ("elisac_stage1.sh", "stage1_object_cache.py", "platform.sh"):
            shutil.copyfile(scripts / name, root / "scripts" / name)
        return root


    def run_cache_key(self, compiler, source, *, root=None, cwd=None, allow_stale=False, extra_env=None, cache_toggle="1", environment_status=0):
        repo_root = Path(__file__).resolve().parent.parent
        wrapper = (repo_root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_prepare\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        if environment_status is None:
            environment = re.search(r"stage1_cache_environment\(\) \{\n.*?^\}", wrapper, re.M | re.S).group()
        else:
            environment = f"stage1_cache_environment() {{ return {environment_status}; }}"
        script = (
            'set -uo pipefail\n'
            'driver_args=("$SOURCE_INPUT" -o "${OUTPUT_DEST:-output.o}")\n'
            'stage1_cache_out=""\n'
            + environment + '\n'
            + function.group()
            + '\nstage1_cache_prepare || exit 7\nprintf "%s" "$stage1_cache_key"\n'
        )
        env = dict(
            os.environ,
            ROOT=str(root if root is not None else compiler.parent.parent),
            BIN=str(compiler),
            ELISA_STAGE1_CACHE_DIR=str(self.source.parent / "object-cache"),
            SOURCE_INPUT=str(source),
            COMPILER_CALL_LOG=str(self.source.parent / "dependency-compiler-calls"),
        )
        if cache_toggle is None:
            env.pop("ELISA_STAGE1_CACHE", None)
        else:
            env["ELISA_STAGE1_CACHE"] = str(cache_toggle)
        if extra_env:
            env.update(extra_env)
        if allow_stale:
            env["ELISA_ALLOW_STALE_STAGE1"] = "1"
        return subprocess.run(["bash", "-c", script], cwd=cwd, env=env, check=False, capture_output=True)


    def cache_key(self, compiler, source, *, root=None, extra_env=None):
        result = self.run_cache_key(compiler, source, root=root, extra_env=extra_env)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout


    def fake_dependency_compiler(self, compiler, source):
        compiler.write_text(
            "#!/bin/bash\n"
            'call_index=0; [[ ! -f "${COMPILER_CALL_LOG:-/dev/null}" ]] || call_index="$(wc -c < "${COMPILER_CALL_LOG:-/dev/null}")"\n'
            'printf x >> "${COMPILER_CALL_LOG:-/dev/null}"\n'
            'out=""; emit="obj"\n'
            'while (($#)); do\n'
            '  case "$1" in\n'
            '    -o) out="$2"; shift 2 ;;\n'
            '    -emit) emit="$2"; shift 2 ;;\n'
            '    *) shift ;;\n'
            '  esac\n'
            'done\n'
            'if [[ "$emit" == deps ]]; then\n'
            '  if [[ -n "${INCLUDED_DEPENDENCY:-}" ]]; then\n'
            '    dependency="${INCLUDED_DEPENDENCY}"\n'
            '    if [[ "${SWITCH_DEPENDENCY_AFTER_FIRST:-0}" == 1 && "$call_index" -ge 1 ]]; then dependency="${SECOND_DEPENDENCY}"; fi\n'
            '    printf "%s\\n%s\\n" "$SOURCE_INPUT" "$dependency" > "$out"\n'
            '  else\n'
            '    printf "%s\\n" "$SOURCE_INPUT" > "$out"\n'
            '  fi\n'
            'fi\n'
        )
        compiler.chmod(0o755)
        source.write_text("def main() -> i64: return 42\n")
        Path(f"{compiler}.provenance.json").write_text('{"schema":"elisa-stage1-provenance-v5"}\n')


    def publish(self):
        self.assertTrue(cache.publish(self.entry, self.source, "key"))


    def refused(self, key="key"):
        self.assertFalse(cache.restore(self.entry, self.output, key))
        self.assertEqual(self.output.read_bytes(), b"previous valid output")
        self.assertFalse(list(self.output.parent.glob("*.incoming.*")))



__all__ = [name for name in globals() if not name.startswith("__")]
