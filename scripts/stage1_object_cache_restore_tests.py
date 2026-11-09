from __future__ import annotations
from stage1_object_cache_test_support import *
import stage1_object_cache_files


class ObjectCacheRestoreTests(CacheTestFixture):
    def test_valid_copy(self):
        self.publish()
        self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())

    def test_restore_declines_symlink_output(self):
        self.publish()
        target = self.output.parent / "output-target.o"
        target.write_bytes(b"previous valid output")
        self.output.unlink()
        self.output.symlink_to(target)
        self.assertFalse(cache.restore(self.entry, self.output, "key"))
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(target.read_bytes(), b"previous valid output")

    def test_restore_declines_hardlinked_output(self):
        self.publish()
        alias = self.output.parent / "output-alias.o"
        os.link(self.output, alias)
        original_inode = self.output.stat().st_ino
        self.assertFalse(cache.restore(self.entry, self.output, "key"))
        self.assertEqual(self.output.stat().st_ino, original_inode)
        self.assertEqual(alias.stat().st_ino, original_inode)
        self.assertEqual(alias.read_bytes(), b"previous valid output")

    def test_restore_does_not_create_missing_output_directories(self):
        self.publish()
        missing_output = self.output.parent / "missing" / "nested.o"
        self.assertFalse(cache.restore(self.entry, missing_output, "key"))
        self.assertFalse(missing_output.parent.exists())

    def test_copy_declines_source_replacement_during_read(self):
        target = self.source.parent / "copy-target"
        replacement = self.source.parent / "replacement.o"
        target.write_bytes(b"")
        original_read = os.read
        changed = False

        def replace_after_read(descriptor, maximum):
            nonlocal changed
            chunk = original_read(descriptor, maximum)
            if chunk and not changed:
                replacement.write_bytes(b"replacement" * 100)
                os.replace(replacement, self.source)
                changed = True
            return chunk

        with patch.object(cache.os, "read", side_effect=replace_after_read):
            with self.assertRaisesRegex(OSError, "source changed"):
                cache.copy_digest(self.source, target)

    def test_copy_declines_replaced_staging_file_before_truncation(self):
        target, identity = cache.temporary(self.source.parent / "copy-target")
        target.unlink()
        target.write_bytes(b"preserve this unrelated file")
        with self.assertRaisesRegex(OSError, "staging file was replaced"):
            cache.copy_digest(self.source, target, target_identity=identity)
        self.assertEqual(target.read_bytes(), b"preserve this unrelated file")

    def test_fifo_cached_object_does_not_block_restore(self):
        self.entry.parent.mkdir(parents=True)
        os.mkfifo(self.entry)
        empty_stream = {"size": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        payload = {
            "schema": cache.SCHEMA,
            "key": "key",
            "object": {
                "size": len(self.source.read_bytes()),
                "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                "mode": 0o644,
            },
            "streams": {"stdout": empty_stream, "stderr": empty_stream},
        }
        Path(str(self.entry) + ".json").write_text(json.dumps(payload))
        try:
            result = subprocess.run(
                [sys.executable, str(Path(cache.__file__)), "restore", str(self.entry), str(self.output), "key"],
                capture_output=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            self.fail("restoring a FIFO cache entry blocked instead of rejecting it")
        self.assertEqual(result.returncode, 1, result.stderr.decode())
        self.assertEqual(self.output.read_bytes(), b"previous valid output")

    def test_fifo_manifest_does_not_block_restore(self):
        self.entry.parent.mkdir(parents=True)
        os.mkfifo(Path(str(self.entry) + ".json"))
        try:
            result = subprocess.run(
                [sys.executable, str(Path(cache.__file__)), "restore", str(self.entry), str(self.output), "key"],
                capture_output=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            self.fail("reading a FIFO cache manifest blocked instead of rejecting it")
        self.assertEqual(result.returncode, 1, result.stderr.decode())
        self.assertEqual(self.output.read_bytes(), b"previous valid output")

    def test_fifo_diagnostic_stream_does_not_block_restore(self):
        stdout = self.source.parent / "stdout"
        stderr = self.source.parent / "stderr"
        stdout.write_bytes(b"cached stdout\n")
        stderr.write_bytes(b"cached stderr\n")
        self.assertTrue(cache.publish(self.entry, self.source, "key", stdout, stderr))
        cached_stderr = Path(str(self.entry) + ".stderr")
        cached_stderr.unlink()
        os.mkfifo(cached_stderr)
        try:
            result = subprocess.run(
                [sys.executable, str(Path(cache.__file__)), "restore", str(self.entry), str(self.output), "key"],
                capture_output=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            self.fail("reading a FIFO diagnostic stream blocked instead of rejecting it")
        self.assertEqual(result.returncode, 1, result.stderr.decode())
        self.assertEqual(self.output.read_bytes(), b"previous valid output")

    def test_restore_preserves_cached_object_permissions(self):
        self.source.chmod(0o751)
        self.publish()
        self.output.chmod(0o600)
        self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o751)

    def test_restore_uses_current_destination_permissions(self):
        self.publish()
        self.output.chmod(0o600)
        staged = self.output.parent / "staged.o"
        staged.write_bytes(b"")
        self.assertTrue(cache.restore(self.entry, staged, "key", destination=self.output))
        self.assertEqual(staged.stat().st_mode & 0o777, 0o600)

    def test_restore_uses_current_umask_for_new_destination(self):
        self.publish()
        staged = self.output.parent / "staged.o"
        staged.write_bytes(b"")
        destination = self.output.parent / "new-output.o"
        previous_mask = os.umask(0o027)
        try:
            self.assertTrue(cache.restore(self.entry, staged, "key", destination=destination))
        finally:
            os.umask(previous_mask)
        self.assertEqual(staged.stat().st_mode & 0o777, 0o640)

    def test_restore_declines_changed_provenance_without_publishing(self):
        self.publish()
        staged = self.output.parent / "staged.o"
        staged.write_bytes(b"staging sentinel")
        before = self.output.read_bytes()
        with patch.object(stage1_object_cache_files, "descriptor_provenance", side_effect=["01", "02"]) as provenance, \
             patch.object(cache, "descriptor_provenance", side_effect=provenance):
            self.assertFalse(cache.restore(self.entry, staged, "key", destination=self.output))
        self.assertEqual(staged.read_bytes(), b"staging sentinel")
        self.assertEqual(self.output.read_bytes(), before)

    def test_output_state_declines_hardlinked_destination(self):
        alias = self.output.parent / "output-alias.o"
        os.link(self.output, alias)
        self.assertIsNone(cache.compiler_output_state(self.output))

    def test_output_state_declines_destination_with_xattrs(self):
        if sys.platform != "darwin" and not (
            sys.platform.startswith("linux") and hasattr(os, "setxattr")
        ):
            self.skipTest("file extended attributes are unavailable")
        try:
            attribute = (
                b"user.elisa-cache-test"
                if sys.platform.startswith("linux")
                else b"com.elisa.cache-test"
            )
            if sys.platform == "darwin" and not hasattr(os, "setxattr"):
                subprocess.run(["/usr/bin/xattr", "-w", attribute.decode(), "preserve", str(self.output)],
                               check=True, capture_output=True)
            else:
                os.setxattr(self.output, attribute, b"preserve")
        except OSError as error:
            self.skipTest(f"cannot set a test extended attribute: {error}")
        self.assertIsNone(cache.compiler_output_state(self.output))

    def test_output_state_declines_present_or_unverifiable_acl(self):
        for acl_state in (True, None):
            with self.subTest(acl_state=acl_state), patch.object(
                stage1_object_cache_files, "descriptor_has_extended_acl", return_value=acl_state
            ):
                self.assertIsNone(cache.compiler_output_state(self.output))

    def test_invalid_cached_permissions_preserve_previous_output(self):
        self.publish()
        stamp = Path(str(self.entry) + ".json")
        metadata = json.loads(stamp.read_text())
        metadata["object"]["mode"] = 0o7777
        stamp.write_text(json.dumps(metadata))
        self.refused()

    def test_cache_declines_symlink_output(self):
        root = self.cache_project()
        source = root / "source.elisa"
        compiler = root / "bin" / "fake-compiler"
        self.fake_dependency_compiler(compiler, source)
        target = self.source.parent / "symlink-target.o"
        output = self.source.parent / "symlink-output.o"
        target.write_bytes(b"prior target")
        output.symlink_to(target)

        result = self.run_cache_key(
            compiler,
            source,
            root=root,
            cache_toggle=None,
            extra_env={"OUTPUT_DEST": str(output)},
        )
        self.assertEqual(result.returncode, 7)
        self.assertTrue(output.is_symlink())
        self.assertEqual(target.read_bytes(), b"prior target")
        self.assertFalse(Path(self.source.parent / "dependency-compiler-calls").exists())

    def test_wrapper_hit_does_not_replace_symlink_output(self):
        root = self.cache_project()
        wrapper = (Path(__file__).resolve().parent.parent / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_restore_if_unchanged\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        entry = root / "cache" / "key.o"
        stdout = self.source.parent / "cached.stdout"
        stderr = self.source.parent / "cached.stderr"
        stdout.write_bytes(b"cached output\n")
        stderr.write_bytes(b"cached warning\n")
        self.assertTrue(cache.publish(entry, self.source, "key", stdout, stderr))

        target = root / "target.o"
        output = root / "output-link.o"
        target.write_bytes(b"prior target")
        output.symlink_to(target)
        script = (
            'set -uo pipefail\n'
            + function.group()
            + '\nstage1_cache_prepare() { stage1_cache_key="key"; stage1_cache_dependency_identity="identity"; return 0; }\n'
            + 'stage1_cache_restore_if_unchanged\n'
        )
        result = subprocess.run(
            ["bash", "-c", script],
            env=dict(
                os.environ,
                ROOT=str(root),
                stage1_cache_entry=str(entry),
                stage1_cache_out=str(output),
                stage1_cache_key="key",
                stage1_cache_dependency_identity="identity",
                stage1_cache_output_state="symlink-is-not-admitted",
            ),
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(output.is_symlink())
        self.assertEqual(target.read_bytes(), b"prior target")
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

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
