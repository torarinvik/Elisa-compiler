#!/usr/bin/env python3
"""Cache admission must never publish partial, corrupt, or mismatched bytes."""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import stage1_object_cache as cache


class CacheIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.entry, self.source, self.output = (root / p for p in ("cache/key.o", "source.o", "output.o"))
        self.source.write_bytes(b"object payload" * 100)
        self.output.write_bytes(b"previous valid output")

    def publish(self):
        self.assertTrue(cache.publish(self.entry, self.source, "key"))

    def refused(self, key="key"):
        self.assertFalse(cache.restore(self.entry, self.output, key))
        self.assertEqual(self.output.read_bytes(), b"previous valid output")
        self.assertFalse(list(self.output.parent.glob("*.incoming.*")))

    def test_valid_copy(self):
        self.publish()
        self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())

    def test_wrapper_publication_requires_unchanged_inputs(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_publish_if_unchanged\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        logs = self.source.parent / "logs"
        logs.mkdir()
        (logs / "stdout").write_bytes(b"compile result\n")
        (logs / "stderr").write_bytes(b"compile warning\n")
        script = function.group() + '\nstage1_cache_prepare() { stage1_cache_key="$TEST_NEXT_KEY"; return "$TEST_PREPARE_RC"; }\nstage1_cache_publish_if_unchanged\n'
        for index, (next_key, prepare_rc, admitted) in enumerate((("key", 0, True), ("edited", 0, False), ("key", 1, False))):
            with self.subTest(next_key=next_key, prepare_rc=prepare_rc):
                entry = self.entry.with_name(f"publication-{index}.o")
                env = dict(os.environ, ROOT=str(root), stage1_cache_key="key", stage1_cache_entry=str(entry), stage1_cache_out=str(self.source), stage1_cache_logs=str(logs), TEST_NEXT_KEY=next_key, TEST_PREPARE_RC=str(prepare_rc))
                subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True)
                self.assertEqual(entry.exists(), admitted)
                self.assertEqual(Path(str(entry) + ".json").exists(), admitted)
                self.assertEqual(self.source.read_bytes(), b"object payload" * 100)

    def test_unreadable_dependency_refuses_cache_identity(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_prepare\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        compiler = self.source.parent / "fake-compiler"
        compiler.write_text('#!/bin/bash\nprintf "%s\\n" "$MISSING_DEPENDENCY" > "$4"\n')
        compiler.chmod(0o755)
        script = 'set -uo pipefail\ndriver_args=(source.elisa -o output.o)\nstage1_cache_out=""\nstage1_cache_environment() { return 1; }\n' + function.group() + '\nif stage1_cache_prepare; then exit 9; fi\n'
        env = dict(os.environ, ROOT=str(root), BIN=str(compiler), ELISA_STAGE1_CACHE="1", MISSING_DEPENDENCY=str(self.source.parent / "missing.elisa"))
        result = subprocess.run(["bash", "-c", script], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b"missing.elisa", result.stderr)

    def test_profile_content_participates_in_cache_identity(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_prepare\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        compiler = self.source.parent / "fake-compiler"
        compiler.write_text('#!/bin/bash\nprintf "%s\\n" "$SOURCE_INPUT" > "$4"\n')
        compiler.chmod(0o755)
        source = self.source.parent / "source.elisa"
        source.write_bytes(b"def main() -> i64: return 42\n")
        profile = self.source.parent / "profile.elisa"
        script = 'set -uo pipefail\ndriver_args=("$SOURCE_INPUT" -o output.o -fprofile-use "$PROFILE_INPUT")\nstage1_cache_out=""\nstage1_cache_environment() { return 1; }\n' + function.group() + '\nstage1_cache_prepare || exit 7\nprintf "%s" "$stage1_cache_key"\n'
        env = dict(os.environ, ROOT=str(root), BIN=str(compiler), ELISA_STAGE1_CACHE="1", SOURCE_INPUT=str(source), PROFILE_INPUT=str(profile))
        keys = []
        for data in (b"ELISA_PGO_V1\n", b"ELISA_PGO_V1\nhot main\n"):
            profile.write_bytes(data)
            result = subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True)
            keys.append(result.stdout)
        self.assertNotEqual(*keys)
        profile.unlink()
        self.assertEqual(subprocess.run(["bash", "-c", script], env=env, capture_output=True).returncode, 7)

    def test_contract_override_participates_in_cache_identity(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_environment\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        values = []
        for forced in ("0", "1"):
            env = {"PATH": os.environ["PATH"], "ELISACORE_FORCE_CONTRACTS": forced, "ELISA_STAGE1_CACHE_DIR": "/ignored/cache", "ELISA_STAGE1_CACHE": "1"}
            result = subprocess.run(["bash", "-c", function.group() + "\nstage1_cache_environment\n"], env=env, check=True, capture_output=True)
            self.assertEqual(result.stdout, f"ELISACORE_FORCE_CONTRACTS={forced}\n".encode())
            values.append(result.stdout)
        self.assertNotEqual(*values)

    def test_corruption_and_truncation(self):
        for payload in (b"corrupt", b"", b"x" * self.source.stat().st_size):
            with self.subTest(payload_size=len(payload)):
                self.publish()
                self.entry.write_bytes(payload)
                self.refused()

    def test_manifest_missing_malformed_or_different_request(self):
        self.publish()
        self.refused("different key")
        stamp = Path(str(self.entry) + ".json")
        for payload in (b"{", b"[]", b"{}", b"x" * 16385):
            stamp.write_bytes(payload)
            self.refused()
        stamp.unlink()
        self.refused()

    def test_partial_or_racing_publication(self):
        self.publish()
        stamp = Path(str(self.entry) + ".json")
        old_metadata = stamp.read_bytes()
        self.source.write_bytes(b"different legitimate output")
        self.publish()
        stamp.write_bytes(old_metadata)
        self.refused()

    def test_cache_path_changes_after_copy(self):
        self.publish()
        original = cache.copy_digest
        def change_after_read(source, target, **kwargs):
            result = original(source, target, **kwargs)
            source.write_bytes(b"corrupted after verified read")
            return result
        with patch.object(cache, "copy_digest", change_after_read):
            self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())

    def test_diagnostic_replay_is_byte_exact(self):
        out, err = self.source.parent / "stdout", self.source.parent / "stderr"
        out.write_bytes(b"result\x00\xff\n")
        err.write_bytes(b"warning one\nwarning two\xfe\n")
        self.assertTrue(cache.publish(self.entry, self.source, "key", out, err))
        stdout, stderr = io.BytesIO(), io.BytesIO()
        self.assertTrue(cache.restore(self.entry, self.output, "key", stdout=stdout, stderr=stderr))
        self.assertEqual(stdout.getvalue(), out.read_bytes())
        self.assertEqual(stderr.getvalue(), err.read_bytes())

    def test_admitted_replay_io_failure_is_not_a_cache_miss(self):
        class FailingStream(io.BytesIO):
            def write(self, data):
                raise OSError("diagnostic sink failed")

        out, err = self.source.parent / "stdout", self.source.parent / "stderr"
        out.write_bytes(b"compile result\n")
        err.write_bytes(b"compile warning\n")
        for failing in ("stderr", "stdout"):
            with self.subTest(failing=failing):
                self.assertTrue(cache.publish(self.entry, self.source, "key", out, err))
                stdout = FailingStream() if failing == "stdout" else io.BytesIO()
                stderr = FailingStream() if failing == "stderr" else io.BytesIO()
                with self.assertRaisesRegex(OSError, "diagnostic sink failed"):
                    cache.restore(self.entry, self.output, "key", stdout=stdout, stderr=stderr)
                self.assertEqual(self.output.read_bytes(), self.source.read_bytes())
                self.assertEqual(stderr.getvalue(), err.read_bytes() if failing == "stdout" else b"")
                self.assertEqual(stdout.getvalue(), b"")
                self.assertFalse(list(self.output.parent.glob("*.incoming.*")))

    def test_bad_diagnostics_never_publish_or_replay(self):
        for name in ("stdout", "stderr"):
            for missing in (False, True):
                with self.subTest(name=name, missing=missing):
                    self.publish()
                    stream = Path(str(self.entry) + "." + name)
                    if missing:
                        stream.unlink()
                    else:
                        stream.write_bytes(b"corrupted diagnostics")
                    stdout, stderr = io.BytesIO(), io.BytesIO()
                    self.assertFalse(cache.restore(self.entry, self.output, "key", stdout=stdout, stderr=stderr))
                    self.assertEqual(self.output.read_bytes(), b"previous valid output")
                    self.assertEqual((stdout.getvalue(), stderr.getvalue()), (b"", b""))
                    self.assertFalse(list(self.output.parent.glob("*.incoming.*")))

    def test_oversized_diagnostics_preserve_previous_entry(self):
        self.publish()
        err = self.source.parent / "stderr"
        err.write_bytes(b"large warning")
        with patch.object(cache, "MAX_DIAGNOSTIC_BYTES", 1):
            self.assertFalse(cache.publish(self.entry, self.source, "key", stderr=err))
        self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertFalse(list(self.entry.parent.glob("*.incoming.*")))

    def test_oversized_object(self):
        self.publish()
        with patch.object(cache, "MAX_OBJECT_BYTES", 1):
            self.refused()


if __name__ == "__main__":
    unittest.main()
