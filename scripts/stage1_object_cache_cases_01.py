from __future__ import annotations
from stage1_object_cache_test_support import *


class ObjectCacheCases1(CacheTestFixture):
    def test_parallel_custom_merger_is_not_cacheable(self):
        root = self.cache_project()
        compiler, source = root / "bin/compiler", root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        merger = root / "merger"
        for content in ("first delegated linker", "replaced delegated linker"):
            merger.write_text(content)
            result = self.run_cache_key(compiler, source, root=root, extra_env={
                "ELISA_STAGE1_JOBS": "2", "ELISA_LD": str(merger),
            }, environment_status=None)
            self.assertEqual(result.returncode, 7, "custom merger admitted without its dependency closure")
        serial = self.run_cache_key(compiler, source, root=root, extra_env={
            "ELISA_STAGE1_JOBS": "1", "ELISA_LD": str(merger),
        }, environment_status=None)
        self.assertEqual(serial.returncode, 0, serial.stderr.decode())


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


    def test_default_parallel_merger_remains_cacheable(self):
        root = self.cache_project()
        compiler, source = root / "bin/compiler", root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        environment = {"ELISA_STAGE1_JOBS": "2", "PATH": "/usr/bin:/bin"}
        first = self.run_cache_key(compiler, source, root=root, extra_env=environment)
        second = self.run_cache_key(compiler, source, root=root, extra_env=environment)
        self.assertEqual(first.returncode, 0, first.stderr.decode())
        self.assertEqual(second.returncode, 0, second.stderr.decode())
        self.assertEqual(first.stdout, second.stdout)


    def test_merger_job_parser_matches_backend_prefix_and_cap(self):
        for value, expected in (("", 1), ("0", 1), ("1", 1), (" 2", 1),
                                ("-2", 1), ("2suffix", 2), ("064", 64),
                                ("999999999999999999999", 64), ("２", 1)):
            self.assertEqual(cache.parallel_emit_jobs(value), expected, value)


    def test_serial_merger_identity_needs_no_external_tool(self):
        with patch.object(cache.shutil, "which", side_effect=AssertionError("serial lookup")):
            self.assertEqual(cache.object_merger_key({"ELISA_STAGE1_JOBS": "1", "ELISA_LD": "anything"}),
                             "serial-object-emission-v1")


    def test_native_merger_same_mtime_replacement_changes_parallel_identity(self):
        native = self.source.parent / "native-ld"
        shutil.copyfile(shutil.which("true"), native)
        native.chmod(0o755)
        read_record = cache.native_merger_record
        environment = {"ELISA_STAGE1_JOBS": "2", "PATH": "/usr/bin"}
        with patch.object(cache.shutil, "which", return_value="/usr/bin/ld"), \
                patch.object(cache, "native_merger_record", side_effect=lambda _: read_record(native)):
            first = cache.object_merger_key(environment, "linux")
            before = native.stat()
            with native.open("ab") as output:
                output.write(b"changed linker contents")
            os.utime(native, ns=(before.st_atime_ns, before.st_mtime_ns))
            second = cache.object_merger_key(environment, "linux")
            self.assertNotEqual(first, second)
            self.assertNotEqual(second, cache.object_merger_key(dict(environment, SDKROOT="other-sdk"), "linux"))
        native.chmod(0o600)
        with self.assertRaises(ValueError):
            read_record(native)


    def test_macos_merger_identity_includes_dispatch_and_selected_tool(self):
        environment = {"ELISA_STAGE1_JOBS": "2", "PATH": "/usr/bin"}
        contents = {"/usr/bin/ld": "dispatch", "/usr/bin/xcrun": "selector", "/selected/ld": "linker"}
        def record(path):
            return {"selected": path, "sha256": hashlib.sha256(contents[path].encode()).hexdigest()}
        with patch.object(cache.shutil, "which", return_value="/usr/bin/ld"), \
                patch.object(cache.os.path, "realpath", side_effect=lambda path: path), \
                patch.object(cache, "native_merger_record", side_effect=record), \
                patch.object(cache.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"/selected/ld\n")):
            original = cache.object_merger_key(environment, "darwin")
            for path in contents:
                contents[path] += " replacement"
                changed = cache.object_merger_key(environment, "darwin")
                self.assertNotEqual(original, changed, path)
                original = changed


    def test_parallel_shell_overrides_and_empty_selector_decline(self):
        for setting in ({"ELISA_LD": ""}, {"BASH_ENV": "/hook"}, {"ENV": "/hook"},
                        {"BASH_FUNC_ld%%": "() { wrapper; }"}, {"ld": "()\n{ wrapper; }"}):
            with self.assertRaises(ValueError):
                cache.object_merger_key(dict(setting, ELISA_STAGE1_JOBS="2"))


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


    def test_fifo_dependency_fingerprint_does_not_block(self):
        fifo = self.source.parent / "dependency.fifo"
        os.mkfifo(fifo)
        script = "import sys; import stage1_object_cache as cache; cache.fingerprint(sys.argv[1])"
        env = dict(os.environ, PYTHONPATH=str(Path(cache.__file__).parent))
        try:
            result = subprocess.run(
                [sys.executable, "-c", script, str(fifo)],
                env=env,
                capture_output=True,
                timeout=2,
            )
        except subprocess.TimeoutExpired:
            self.fail("fingerprinting a FIFO blocked instead of declining it")
        self.assertNotEqual(result.returncode, 0)


    def test_dependency_report_path_limit_is_checked_during_scan(self):
        report = self.source.parent / "dependencies.txt"
        report.write_bytes(b"source\n" * (cache.MAX_DEPENDENCIES + 1))
        with self.assertRaisesRegex(ValueError, "path limit"):
            cache.dependencies_from_output(report, self.source)


    def test_dependency_report_rejects_multiple_trailing_newlines(self):
        report = self.source.parent / "dependencies.txt"
        report.write_bytes((str(self.source) + "\n\n").encode())
        with self.assertRaisesRegex(ValueError, "empty path"):
            cache.dependencies_from_output(report, self.source)


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


    @unittest.skipUnless(sys.platform == "darwin", "macOS provenance metadata")
    def test_restore_declines_changed_provenance_without_publishing(self):
        self.publish()
        staged = self.output.parent / "staged.o"
        staged.write_bytes(b"staging sentinel")
        before = self.output.read_bytes()
        with patch.object(cache, "descriptor_provenance", side_effect=["01", "02"]):
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
                cache, "descriptor_has_extended_acl", return_value=acl_state
            ):
                self.assertIsNone(cache.compiler_output_state(self.output))


    def test_invalid_cached_permissions_preserve_previous_output(self):
        self.publish()
        stamp = Path(str(self.entry) + ".json")
        metadata = json.loads(stamp.read_text())
        metadata["object"]["mode"] = 0o7777
        stamp.write_text(json.dumps(metadata))
        self.refused()


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


    def test_unreadable_dependency_refuses_cache_identity(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        missing = self.source.parent / "missing.elisa"
        result = self.run_cache_key(compiler, source, root=root, extra_env={"INCLUDED_DEPENDENCY": str(missing)})
        self.assertEqual(result.returncode, 7)
        self.assertFalse(list((self.source.parent / "object-cache").rglob("*.json")))


    def test_symlink_loop_dependency_falls_back_without_cache_identity(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        loop = root / "include-loop.elisa"
        loop.symlink_to(loop)

        result = self.run_cache_key(compiler, source, root=root, extra_env={"INCLUDED_DEPENDENCY": str(loop)})

        self.assertEqual(result.returncode, 7)
        self.assertEqual((self.source.parent / "dependency-compiler-calls").read_text(), "x")
        self.assertFalse(list((self.source.parent / "object-cache").rglob("*.json")))


    def test_wrapper_rejects_dependency_graph_changes_between_discovery_passes(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        first = root / "first.elisa"
        second = root / "second.elisa"
        self.fake_dependency_compiler(compiler, source)
        first.write_text("const FIRST: i64 = 1\n")
        second.write_text("const SECOND: i64 = 2\n")
        log = self.source.parent / "dependency-compiler-calls"

        result = self.run_cache_key(
            compiler,
            source,
            root=root,
            extra_env={
                "INCLUDED_DEPENDENCY": str(first),
                "SECOND_DEPENDENCY": str(second),
                "SWITCH_DEPENDENCY_AFTER_FIRST": "1",
            },
        )

        self.assertEqual(result.returncode, 7)
        self.assertEqual(log.read_text(), "xx")
        self.assertFalse(list((self.source.parent / "object-cache").rglob("*.json")))


    def test_dependency_index_reuses_graph_and_invalidates_changed_files(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        dependency = root / "included.elisa"
        self.fake_dependency_compiler(compiler, source)
        dependency.write_text("const VALUE: i64 = 1\n")
        log = self.source.parent / "dependency-compiler-calls"
        environment = {"INCLUDED_DEPENDENCY": str(dependency)}

        first = self.cache_key(compiler, source, root=root, extra_env=environment)
        self.assertEqual(log.read_text(), "xx")
        second = self.cache_key(compiler, source, root=root, extra_env=environment)
        self.assertEqual(second, first)
        self.assertEqual(log.read_text(), "xx")

        replacement = root / "replacement.elisa"
        replacement.write_bytes(dependency.read_bytes())
        os.replace(replacement, dependency)
        same_content = self.cache_key(compiler, source, root=root, extra_env=environment)
        self.assertEqual(same_content, first)
        self.assertEqual(log.read_text(), "xxxx")

        dependency.write_text("const VALUE: i64 = 2\n")
        third = self.cache_key(compiler, source, root=root, extra_env=environment)
        self.assertNotEqual(third, first)
        self.assertEqual(log.read_text(), "xxxxxx")


