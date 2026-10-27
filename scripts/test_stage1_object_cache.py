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

    def run_cache_key(self, compiler, source, *, root=None, cwd=None, allow_stale=False, extra_env=None, cache_toggle="1"):
        repo_root = Path(__file__).resolve().parent.parent
        wrapper = (repo_root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_prepare\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        script = (
            'set -uo pipefail\n'
            'driver_args=("$SOURCE_INPUT" -o "${OUTPUT_DEST:-output.o}")\n'
            'stage1_cache_out=""\n'
            'stage1_cache_environment() { return 1; }\n'
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

    def test_valid_copy(self):
        self.publish()
        self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())

    def test_restore_preserves_cached_object_permissions(self):
        self.source.chmod(0o751)
        self.publish()
        self.output.chmod(0o600)
        self.assertTrue(cache.restore(self.entry, self.output, "key"))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o751)

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
            + '\nstage1_cache_prepare() { stage1_cache_key="$TEST_NEXT_KEY"; stage1_cache_dependency_identity="$TEST_NEXT_IDENTITY"; return 0; }\n'
            + 'stage1_cache_restore_if_unchanged\n'
        )

        output.write_bytes(b"prior output")
        same = subprocess.run(
            ["bash", "-c", script],
            env=dict(os.environ, ROOT=str(root), stage1_cache_entry=str(entry), stage1_cache_out=str(output), stage1_cache_key="key", stage1_cache_dependency_identity="identity", TEST_NEXT_KEY="key", TEST_NEXT_IDENTITY="identity"),
            capture_output=True,
        )
        self.assertEqual(same.returncode, 0, same.stderr.decode())
        self.assertEqual(output.read_bytes(), self.source.read_bytes())
        self.assertEqual(same.stdout, b"cached output\n")
        self.assertEqual(same.stderr, b"cached warning\n")

        output.write_bytes(b"prior output")
        changed = subprocess.run(
            ["bash", "-c", script],
            env=dict(os.environ, ROOT=str(root), stage1_cache_entry=str(entry), stage1_cache_out=str(output), stage1_cache_key="key", stage1_cache_dependency_identity="identity", TEST_NEXT_KEY="key", TEST_NEXT_IDENTITY="replaced"),
            capture_output=True,
        )
        self.assertEqual(changed.returncode, 1)
        self.assertEqual(output.read_bytes(), b"prior output")
        self.assertEqual(changed.stdout, b"")
        self.assertEqual(changed.stderr, b"")

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
        script = 'set -uo pipefail\ndriver_args=("$SOURCE_INPUT" -o output.o -fprofile-use "$PROFILE_INPUT")\nstage1_cache_out=""\nstage1_cache_environment() { return 1; }\n' + function.group() + '\nstage1_cache_prepare || exit 7\nprintf "%s" "$stage1_cache_key"\n'
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
            env = {"PATH": os.environ["PATH"], "ELISACORE_FORCE_CONTRACTS": forced, "ELISA_STAGE1_CACHE_DIR": "/ignored/cache", "ELISA_STAGE1_CACHE": "1"}
            result = subprocess.run(["bash", "-c", function.group() + "\nstage1_cache_environment\n"], env=env, check=True, capture_output=True)
            self.assertEqual(result.stdout, f"ELISACORE_FORCE_CONTRACTS={forced}\n".encode())
            values.append(result.stdout)
        self.assertNotEqual(*values)

    def test_codegen_env_flags_participate_in_cache_identity(self):
        root = Path(__file__).resolve().parent.parent
        wrapper = (root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_environment\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        for name, value in (("ELISACORE_FAST_MATH", "1"), ("ELISACORE_STRICT_FP", "1"), ("ELISACORE_NOALIAS_MUTABLE_REFS", "1"), ("ELISACORE_FORCE_BOUNDS_CHECK", "1"), ("ELISACORE_OVERFLOW", "wrap"), ("ELISACORE_TARGET_CPU", "generic")):
            env = {"PATH": os.environ["PATH"], name: value}
            result = subprocess.run(["bash", "-c", function.group() + "\nstage1_cache_environment\n"], env=env, check=True, capture_output=True)
            self.assertEqual(result.stdout, f"{name}={value}\n".encode(), name)

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
