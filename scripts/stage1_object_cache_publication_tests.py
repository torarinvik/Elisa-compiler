from __future__ import annotations
from stage1_object_cache_test_support import *


class ObjectCachePublicationTests(CacheTestFixture):
    def test_parallel_path_launcher_is_not_cacheable(self):
        root = self.cache_project()
        compiler, source = root / "bin/compiler", root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        launcher = root / "bin/ld"
        launcher.write_text("#!/bin/sh\nexec /custom/delegated-ld \"$@\"\n")
        launcher.chmod(0o755)
        result = self.run_cache_key(compiler, source, root=root, extra_env={
            "ELISA_STAGE1_JOBS": "2suffix", "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
        })
        self.assertEqual(result.returncode, 7, "PATH launcher admitted without its delegate identity")

    def test_parallel_shell_overrides_and_empty_selector_decline(self):
        for setting in ({"ELISA_LD": ""}, {"BASH_ENV": "/hook"}, {"ENV": "/hook"},
                        {"BASH_FUNC_ld%%": "() { wrapper; }"}, {"ld": "()\n{ wrapper; }"}):
            with self.assertRaises(ValueError):
                cache.object_merger_key(dict(setting, ELISA_STAGE1_JOBS="2"))

    def test_wrapper_publication_requires_unchanged_inputs(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_publish_if_unchanged\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        logs = self.source.parent / "logs"
        logs.mkdir()
        (logs / "stdout").write_bytes(b"compile result\n")
        (logs / "stderr").write_bytes(b"compile warning\n")
        script = function.group() + '\nstage1_cache_prepare() { stage1_cache_key="$TEST_NEXT_KEY"; stage1_cache_dependency_identity="$TEST_NEXT_IDENTITY"; return "$TEST_PREPARE_RC"; }\nstage1_cache_publish_if_unchanged\n'
        cases = (
            ("key", "identity", 0, True),
            ("edited", "identity", 0, False),
            ("key", "replaced", 0, False),
            ("key", "identity", 1, False),
        )
        for index, (next_key, next_identity, prepare_rc, admitted) in enumerate(cases):
            with self.subTest(next_key=next_key, next_identity=next_identity, prepare_rc=prepare_rc):
                entry = self.entry.with_name(f"publication-{index}.o")
                cache_dir = entry.parent / f"publication-cache-{index}"
                env = dict(os.environ, ROOT=str(root), stage1_cache_key="key", stage1_cache_dependency_identity="identity", stage1_cache_entry=str(entry), stage1_cache_dir=str(cache_dir), stage1_cache_out=str(self.source), stage1_cache_logs=str(logs), TEST_NEXT_KEY=next_key, TEST_NEXT_IDENTITY=next_identity, TEST_PREPARE_RC=str(prepare_rc))
                subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True)
                published_entry = cache_dir / f"{next_key}.o"
                self.assertEqual(published_entry.exists(), admitted)
                self.assertEqual(Path(str(published_entry) + ".json").exists(), admitted)
                self.assertFalse(entry.exists())
                self.assertEqual(self.source.read_bytes(), b"object payload" * 100)

    def test_wrapper_hit_rechecks_inputs_before_publishing_object_or_diagnostics(self):
        root = self.cache_project()
        wrapper = (Path(__file__).resolve().parent.parent / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_restore_if_unchanged\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        entry = root / "cache" / "key.o"
        output = root / "output.o"
        stdout = self.source.parent / "cached.stdout"
        stderr = self.source.parent / "cached.stderr"
        stdout.write_bytes(b"cached output\n")
        stderr.write_bytes(b"cached warning\n")
        self.assertTrue(cache.publish(entry, self.source, "key", stdout, stderr))
        script = (
            'set -uo pipefail\n'
            + function.group()
            + '\nstage1_cache_prepare() { stage1_cache_key="$TEST_NEXT_KEY"; stage1_cache_dependency_identity="$TEST_NEXT_IDENTITY"; stage1_cache_output_state="$TEST_NEXT_OUTPUT_STATE"; return 0; }\n'
            + 'stage1_cache_restore_if_unchanged\n'
        )

        output.write_bytes(b"prior output")
        output.chmod(0o600)
        same = subprocess.run(
            ["bash", "-c", script],
            env=dict(os.environ, ROOT=str(root), stage1_cache_entry=str(entry), stage1_cache_out=str(output), stage1_cache_key="key", stage1_cache_dependency_identity="identity", stage1_cache_output_state="output-state", TEST_NEXT_KEY="key", TEST_NEXT_IDENTITY="identity", TEST_NEXT_OUTPUT_STATE="output-state"),
            capture_output=True,
        )
        self.assertEqual(same.returncode, 0, same.stderr.decode())
        self.assertEqual(output.read_bytes(), self.source.read_bytes())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(same.stdout, b"cached output\n")
        self.assertEqual(same.stderr, b"cached warning\n")

        output.write_bytes(b"prior output")
        changed = subprocess.run(
            ["bash", "-c", script],
            env=dict(os.environ, ROOT=str(root), stage1_cache_entry=str(entry), stage1_cache_out=str(output), stage1_cache_key="key", stage1_cache_dependency_identity="identity", stage1_cache_output_state="output-state", TEST_NEXT_KEY="key", TEST_NEXT_IDENTITY="replaced", TEST_NEXT_OUTPUT_STATE="output-state"),
            capture_output=True,
        )
        self.assertEqual(changed.returncode, 1)
        self.assertEqual(output.read_bytes(), b"prior output")
        self.assertEqual(changed.stdout, b"")
        self.assertEqual(changed.stderr, b"")

        output.write_bytes(b"prior output")
        mode_changed = subprocess.run(
            ["bash", "-c", script],
            env=dict(os.environ, ROOT=str(root), stage1_cache_entry=str(entry), stage1_cache_out=str(output), stage1_cache_key="key", stage1_cache_dependency_identity="identity", stage1_cache_output_state="output-state", TEST_NEXT_KEY="key", TEST_NEXT_IDENTITY="identity", TEST_NEXT_OUTPUT_STATE="new-output-state"),
            capture_output=True,
        )
        self.assertEqual(mode_changed.returncode, 1)
        self.assertEqual(output.read_bytes(), b"prior output")
        self.assertEqual(mode_changed.stdout, b"")
        self.assertEqual(mode_changed.stderr, b"")

    def test_cache_skips_unattested_products(self):
        root = self.cache_project()
        source = root / "source.elisa"
        compiler = root / "bin" / "fake-compiler"
        self.fake_dependency_compiler(compiler, source)
        self.assertEqual(self.run_cache_key(compiler, source, root=root).returncode, 0)
        stale = self.run_cache_key(compiler, source, root=root, allow_stale=True)
        self.assertEqual(stale.returncode, 7)

        external = root / "external" / "bin" / "fake-compiler"
        external.parent.mkdir(parents=True)
        self.fake_dependency_compiler(external, source)
        outside_root = self.run_cache_key(external, source, root=root)
        self.assertEqual(outside_root.returncode, 7)
        path_traversal = root / "bin" / ".." / "external" / "bin" / "fake-compiler"
        traversal_result = self.run_cache_key(path_traversal, source, root=root)
        self.assertEqual(traversal_result.returncode, 7)
        symlink = root / "bin" / "external-compiler"
        symlink.symlink_to(external)
        symlink_result = self.run_cache_key(symlink, source, root=root)
        self.assertEqual(symlink_result.returncode, 7)

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
