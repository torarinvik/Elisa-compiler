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
        helper = Path(__file__).resolve().parent / "stage1_object_cache.py"
        shutil.copyfile(helper, root / "scripts" / helper.name)
        return root

    def run_cache_key(self, compiler, source, *, root=None, allow_stale=False, extra_env=None):
        repo_root = Path(__file__).resolve().parent.parent
        wrapper = (repo_root / "scripts/elisac_stage1.sh").read_text()
        function = re.search(r"stage1_cache_prepare\(\) \{\n.*?^\}", wrapper, re.M | re.S)
        self.assertIsNotNone(function)
        script = (
            'set -uo pipefail\n'
            'driver_args=("$SOURCE_INPUT" -o output.o)\n'
            'stage1_cache_out=""\n'
            'stage1_cache_environment() { return 1; }\n'
            + function.group()
            + '\nstage1_cache_prepare || exit 7\nprintf "%s" "$stage1_cache_key"\n'
        )
        env = dict(
            os.environ,
            ROOT=str(root if root is not None else compiler.parent.parent),
            BIN=str(compiler),
            ELISA_STAGE1_CACHE="1",
            ELISA_STAGE1_CACHE_DIR=str(self.source.parent / "object-cache"),
            SOURCE_INPUT=str(source),
            COMPILER_CALL_LOG=str(self.source.parent / "dependency-compiler-calls"),
        )
        if extra_env:
            env.update(extra_env)
        if allow_stale:
            env["ELISA_ALLOW_STALE_STAGE1"] = "1"
        return subprocess.run(["bash", "-c", script], env=env, check=False, capture_output=True)

    def cache_key(self, compiler, source, *, root=None, extra_env=None):
        result = self.run_cache_key(compiler, source, root=root, extra_env=extra_env)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result.stdout

    def fake_dependency_compiler(self, compiler, source):
        compiler.write_text(
            "#!/bin/bash\n"
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
            '    printf "%s\\n%s\\n" "$SOURCE_INPUT" "$INCLUDED_DEPENDENCY" > "$out"\n'
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
        root = self.cache_project()
        compiler = root / "bin" / "fake-compiler"
        source = root / "source.elisa"
        self.fake_dependency_compiler(compiler, source)
        missing = self.source.parent / "missing.elisa"
        result = self.run_cache_key(compiler, source, root=root, extra_env={"INCLUDED_DEPENDENCY": str(missing)})
        self.assertEqual(result.returncode, 7)
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
        self.assertEqual(log.read_text(), "x")
        second = self.cache_key(compiler, source, root=root, extra_env=environment)
        self.assertEqual(second, first)
        self.assertEqual(log.read_text(), "x")

        dependency.write_text("const VALUE: i64 = 2\n")
        third = self.cache_key(compiler, source, root=root, extra_env=environment)
        self.assertNotEqual(third, first)
        self.assertEqual(log.read_text(), "xx")

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
