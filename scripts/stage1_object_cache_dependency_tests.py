from __future__ import annotations
from stage1_object_cache_test_support import *


class ObjectCacheDependencyTests(CacheTestFixture):
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
