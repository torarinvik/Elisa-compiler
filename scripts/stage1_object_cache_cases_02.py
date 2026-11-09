from __future__ import annotations
from stage1_object_cache_test_support import *


class ObjectCacheCases2(CacheTestFixture):
    def test_dependency_index_reuses_hashes_when_filesystem_identity_is_unchanged(self):
        root = self.source.parent
        source = root / "root.elisa"
        dependency = root / "included.elisa"
        report = root / "deps.txt"
        index = root / "deps.json"
        source.write_text("source\n")
        dependency.write_text("dependency\n")
        report.write_text(f"{source}\n{dependency}\n")
        graph = cache.store_dependencies(index, "base", report, source)

        # A cache hit only needs stat identity checks; unchanged files should not
        # be streamed through SHA-256 again.
        with patch("stage1_object_cache.fingerprint", side_effect=AssertionError("unexpected rehash")):
            self.assertEqual(cache.read_dependencies(index, "base", source), graph)


    def test_dependency_index_rehashes_when_filesystem_identity_changes(self):
        root = self.source.parent
        source = root / "root.elisa"
        dependency = root / "included.elisa"
        report = root / "deps.txt"
        index = root / "deps.json"
        source.write_text("source\n")
        dependency.write_text("dependency\n")
        report.write_text(f"{source}\n{dependency}\n")
        cache.store_dependencies(index, "base", report, source)
        previous = dependency.stat()
        dependency.write_text("1234567890\n")
        os.utime(dependency, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        self.assertEqual(dependency.stat().st_mtime_ns, previous.st_mtime_ns)
        self.assertNotEqual(dependency.stat().st_ctime_ns, previous.st_ctime_ns)

        with patch("stage1_object_cache.fingerprint", wraps=cache.fingerprint) as fingerprint:
            self.assertIsNone(cache.read_dependencies(index, "base", source))
        fingerprint.assert_called_once()


    def test_relative_dependency_paths_reuse_index_and_invalidate_changes(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        dependency = root / "included.elisa"
        self.fake_dependency_compiler(compiler, source)
        dependency.write_text("const VALUE: i64 = 1\n")
        log = self.source.parent / "dependency-compiler-calls"
        environment = {"INCLUDED_DEPENDENCY": dependency.name}

        first = self.run_cache_key(compiler, source.name, root=root, cwd=root, extra_env=environment)
        self.assertEqual(first.returncode, 0, first.stderr.decode())
        self.assertEqual(log.read_text(), "xx")

        second = self.run_cache_key(compiler, source.name, root=root, cwd=root, extra_env=environment)
        self.assertEqual(second.returncode, 0, second.stderr.decode())
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(log.read_text(), "xx")

        dependency.write_text("const VALUE: i64 = 2\n")
        third = self.run_cache_key(compiler, source.name, root=root, cwd=root, extra_env=environment)
        self.assertEqual(third.returncode, 0, third.stderr.decode())
        self.assertNotEqual(third.stdout, first.stdout)
        self.assertEqual(log.read_text(), "xxxx")


    def test_dependency_index_tracks_symlink_retargeting(self):
        root = self.source.parent
        source = root / "root.elisa"
        first = root / "first.elisa"
        second = root / "second.elisa"
        link = root / "included.elisa"
        report = root / "deps.txt"
        index = root / "deps.json"
        source.write_text("def main() -> i64: return 0\n")
        first.write_text("const VALUE: i64 = 1\n")
        second.write_text("const VALUE: i64 = 2\n")
        link.symlink_to(first)
        report.write_text(f"{source}\n{link}\n")
        graph = cache.store_dependencies(index, "base", report, source)
        self.assertEqual(cache.read_dependencies(index, "base", source), graph)

        link.unlink()
        link.symlink_to(second)
        self.assertIsNone(cache.read_dependencies(index, "base", source))


    def test_dependency_index_invalidates_same_content_replacement(self):
        root = self.source.parent
        source = root / "root.elisa"
        dependency = root / "included.elisa"
        replacement = root / "replacement.elisa"
        report = root / "deps.txt"
        index = root / "deps.json"
        source.write_text("source\n")
        dependency.write_text("const VALUE: i64 = 1\n")
        report.write_text(f"{source}\n{dependency}\n")
        graph = cache.store_dependencies(index, "base", report, source)
        self.assertEqual(cache.read_dependencies(index, "base", source), graph)

        # Model an editor rewriting a file during compilation, then restoring its
        # original bytes before the postflight check. Content alone cannot detect it.
        replacement.write_bytes(dependency.read_bytes())
        os.replace(replacement, dependency)
        self.assertIsNone(cache.read_dependencies(index, "base", source))


    def test_dependency_confirmation_publishes_only_a_stable_two_pass_snapshot(self):
        root = self.source.parent
        source = root / "root.elisa"
        dependency = root / "included.elisa"
        first_report = root / "deps-first.txt"
        second_report = root / "deps-second.txt"
        snapshot = root / "deps-snapshot.json"
        index = root / "deps-index.json"
        source.write_text("source\n")
        dependency.write_text("const VALUE: i64 = 1\n")
        first_report.write_text(f"{source}\n{dependency}\n")
        second_report.write_text(first_report.read_text())

        admitted = cache.store_dependencies(snapshot, "base", first_report, source)
        confirmed = cache.confirm_dependencies(snapshot, index, "base", second_report, source)
        self.assertEqual(confirmed, admitted)
        self.assertEqual(cache.read_dependencies(index, "base", source), admitted)


    def test_dependency_confirmation_rejects_changed_inputs_and_include_sets(self):
        root = self.source.parent
        source = root / "root.elisa"
        first = root / "first.elisa"
        second = root / "second.elisa"
        replacement = root / "replacement.elisa"
        first_report = root / "deps-first.txt"
        second_report = root / "deps-second.txt"
        snapshot = root / "deps-snapshot.json"
        index = root / "deps-index.json"
        source.write_text("source\n")
        first.write_text("const VALUE: i64 = 1\n")
        second.write_text("const VALUE: i64 = 1\n")
        first_report.write_text(f"{source}\n{first}\n")
        second_report.write_text(first_report.read_text())
        cache.store_dependencies(snapshot, "base", first_report, source)

        replacement.write_bytes(first.read_bytes())
        os.replace(replacement, first)
        self.assertIsNone(cache.confirm_dependencies(snapshot, index, "base", second_report, source))
        self.assertFalse(index.exists())

        cache.store_dependencies(snapshot, "base", first_report, source)
        second_report.write_text(f"{source}\n{second}\n")
        self.assertIsNone(cache.confirm_dependencies(snapshot, index, "base", second_report, source))
        self.assertFalse(index.exists())


    def test_oversized_dependency_index_still_returns_current_digests(self):
        root = self.source.parent
        source = root / "root.elisa"
        report = root / "deps.txt"
        index = root / "deps.json"
        source.write_text("source\n")
        report.write_text(f"{source}\n")

        with patch.object(cache, "MAX_DEPENDENCY_INDEX_BYTES", report.stat().st_size + 1):
            graph, identity = cache.store_dependencies(index, "base", report, source)

        self.assertRegex(graph, r"^[0-9a-f]{64}$")
        self.assertRegex(identity, r"^[0-9a-f]{64}$")
        self.assertFalse(index.exists())


    def test_dependency_index_supports_relative_paths_in_the_same_directory(self):
        root = self.source.parent
        source = root / "relative-root.elisa"
        dependency = root / "relative-include.elisa"
        report = root / "relative-deps.txt"
        index = root / "relative-deps.json"
        source.write_text("source\n")
        dependency.write_text("dependency\n")
        report.write_text(f"{source.name}\n{dependency.name}\n")
        with patch("os.getcwd", return_value=str(root)):
            graph = cache.store_dependencies(index, "base", report, source.name)
            self.assertEqual(cache.read_dependencies(index, "base", source.name), graph)
            self.assertIsNone(cache.read_dependencies(index, "base", "missing/../relative-root.elisa"))


    def test_dependency_index_rejects_bad_root_and_corruption(self):
        root = self.source.parent
        source = root / "root.elisa"
        other = root / "other.elisa"
        report = root / "deps.txt"
        index = root / "deps.json"
        source.write_text("source\n")
        other.write_text("other\n")
        report.write_text(f"{other}\n{source}\n")
        with self.assertRaisesRegex(ValueError, "does not begin with its root"):
            cache.store_dependencies(index, "base", report, source)

        report.write_text(f"{source}\n")
        cache.store_dependencies(index, "base", report, source)
        index.write_text("{")
        self.assertIsNone(cache.read_dependencies(index, "base", source))


    def test_profile_content_participates_in_cache_identity(self):
        repo_root = Path(__file__).resolve().parent.parent
        wrapper = (repo_root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_prepare\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        profile = root / "profile.elisa"
        script = 'set -uo pipefail\ndriver_args=("$SOURCE_INPUT" -o output.o -fprofile-use "$PROFILE_INPUT")\nstage1_cache_out=""\nstage1_cache_environment() { return 0; }\n' + function.group() + '\nstage1_cache_prepare || exit 7\nprintf "%s" "$stage1_cache_key"\n'
        env = dict(os.environ, ROOT=str(root), BIN=str(compiler), ELISA_STAGE1_CACHE="1", SOURCE_INPUT=str(source), PROFILE_INPUT=str(profile))
        ordinary_script = script.replace(' -fprofile-use "$PROFILE_INPUT"', '')
        ordinary = subprocess.run(["bash", "-c", ordinary_script], env=env, check=True, capture_output=True)
        self.assertRegex(ordinary.stdout.decode(), r"^[0-9a-f]{64}$")
        keys = []
        for data in (b"ELISA_PGO_V1\n", b"ELISA_PGO_V1\nhot main\n"):
            profile.write_bytes(data)
            result = subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True)
            keys.append(result.stdout)
        self.assertNotEqual(*keys)
        profile.unlink()
        self.assertEqual(subprocess.run(["bash", "-c", script], env=env, capture_output=True).returncode, 7)


    def test_same_path_llvm_replacement_changes_cache_identity(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        library = root / "libLLVM.dylib"
        library.write_bytes(b"LLVM shared library v1")
        manifest = Path(f"{compiler}.provenance.json")

        def record_toolchain():
            toolchain = {
                "link_libraries": [{
                    "path": str(library.resolve()),
                    "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
                }],
            }
            manifest.write_text(json.dumps({"schema": "elisa-stage1-provenance-v5", "llvm_toolchain": toolchain}))

        record_toolchain()
        first_key = self.cache_key(compiler, source, root=root).decode()
        self.assertTrue(cache.publish(self.entry, self.source, first_key))
        before = library.stat()
        library.write_bytes(b"LLVM shared library v2")
        os.utime(library, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = library.stat()
        self.assertEqual(after.st_size, before.st_size)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
        self.assertNotEqual(after.st_ctime_ns, before.st_ctime_ns)
        record_toolchain()
        second_key = self.cache_key(compiler, source, root=root).decode()
        self.assertNotEqual(first_key, second_key)
        self.assertFalse(cache.restore(self.entry, self.output, second_key))
        self.assertEqual(self.output.read_bytes(), b"previous valid output")


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


    def test_cache_is_opt_in_and_can_be_enabled_explicitly(self):
        root = self.cache_project()
        source = root / "source.elisa"
        compiler = root / "bin" / "fake-compiler"
        self.fake_dependency_compiler(compiler, source)

        disabled_by_default = self.run_cache_key(compiler, source, root=root, cache_toggle=None)
        self.assertEqual(disabled_by_default.returncode, 7)
        calls = Path(self.source.parent / "dependency-compiler-calls")
        self.assertFalse(calls.exists())

        enabled = self.run_cache_key(compiler, source, root=root, cache_toggle="1")
        self.assertEqual(enabled.returncode, 0, enabled.stderr.decode())
        compiler_calls = calls.read_bytes()
        self.assertTrue(compiler_calls)

        disabled = self.run_cache_key(compiler, source, root=root, cache_toggle="0")
        self.assertEqual(disabled.returncode, 7)
        self.assertEqual(calls.read_bytes(), compiler_calls)


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


    def test_contract_override_participates_in_cache_identity(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_environment\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        values = []
        for forced in ("0", "1"):
            env = {"PATH": os.environ["PATH"], "ROOT": str(root), "ELISACORE_FORCE_CONTRACTS": forced, "ELISA_STAGE1_CACHE_DIR": "/ignored/cache", "ELISA_STAGE1_CACHE": "1"}
            result = subprocess.run(["bash", "-c", function.group() + "\nstage1_cache_environment\n"], env=env, check=True, capture_output=True)
            self.assertEqual(result.stdout, cache.environment_key({b"ELISACORE_FORCE_CONTRACTS": forced.encode()}))
            values.append(result.stdout)
        self.assertNotEqual(*values)


    def test_multiline_environment_cannot_impersonate_another_setting(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_environment\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        configurations = (
            {"ELISACORE_OVERFLOW": "wrap\nELISACORE_FORCE_BOUNDS_CHECK=1"},
            {"ELISACORE_OVERFLOW": "wrap", "ELISACORE_FORCE_BOUNDS_CHECK": "1"},
        )
        identities = []
        for configuration in configurations:
            result = subprocess.run(
                ["bash", "-c", function.group() + "\nstage1_cache_environment\n"],
                env={"PATH": os.environ["PATH"], "ROOT": str(root), **configuration},
                check=True, capture_output=True,
            )
            identities.append(result.stdout)
        self.assertNotEqual(*identities)


    def test_multiline_environment_changes_complete_cache_key(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        keys = []
        with patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            for configuration in (
                {"ELISACORE_OVERFLOW": "wrap\nELISACORE_FORCE_BOUNDS_CHECK=1"},
                {"ELISACORE_OVERFLOW": "wrap", "ELISACORE_FORCE_BOUNDS_CHECK": "1"},
            ):
                result = self.run_cache_key(compiler, source, root=root,
                                            extra_env=configuration, environment_status=None)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertRegex(result.stdout.decode(), r"^[0-9a-f]{64}$")
                keys.append(result.stdout)
        self.assertNotEqual(*keys)


    def test_environment_serialization_failure_declines_cache(self):
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        result = self.run_cache_key(compiler, source, root=root, environment_status=1)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, b"")
        self.assertFalse((self.source.parent / "dependency-compiler-calls").exists())


    def test_environment_identity_preserves_bytes_and_empty_values(self):
        self.assertNotEqual(cache.environment_key({}), cache.environment_key({b"ELISA_FLAG": b""}))
        self.assertNotEqual(cache.environment_key({b"ELISA_FLAG": b"\xff"}),
                            cache.environment_key({b"ELISA_FLAG": b"\xfe"}))
        first = {b"ELISA_A": b"one\ntwo=three", b"ELISACORE_Z": b""}
        self.assertEqual(cache.environment_key(first), cache.environment_key(dict(reversed(list(first.items())))))
        self.assertEqual(cache.environment_key(first), cache.environment_key({
            **first, b"ELISA_STAGE1_CACHE": b"1", b"ELISA_STAGE1_CACHE_DIR": b"/elsewhere", b"PATH": b"ignored",
        }))


    def test_codegen_env_flags_participate_in_cache_identity(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_environment\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        for name, value in (("ELISACORE_FAST_MATH", "1"), ("ELISACORE_STRICT_FP", "1"), ("ELISACORE_NOALIAS_MUTABLE_REFS", "1"), ("ELISACORE_FORCE_BOUNDS_CHECK", "1"), ("ELISACORE_OVERFLOW", "wrap"), ("ELISACORE_TARGET_CPU", "generic")):
            env = {"PATH": os.environ["PATH"], "ROOT": str(root), name: value}
            result = subprocess.run(["bash", "-c", function.group() + "\nstage1_cache_environment\n"], env=env, check=True, capture_output=True)
            self.assertEqual(result.stdout, cache.environment_key({name.encode(): value.encode()}), name)


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


