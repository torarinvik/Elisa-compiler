from __future__ import annotations
from stage1_object_cache_test_support import *
import stage1_object_cache_merger


class ObjectCacheIdentityTests(CacheTestFixture):
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
                patch.object(stage1_object_cache_merger, "native_merger_record", side_effect=lambda _: read_record(native)):
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
                patch.object(stage1_object_cache_merger, "native_merger_record", side_effect=record), \
                patch.object(cache.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"/selected/ld\n")):
            original = cache.object_merger_key(environment, "darwin")
            for path in contents:
                contents[path] += " replacement"
                changed = cache.object_merger_key(environment, "darwin")
                self.assertNotEqual(original, changed, path)
                original = changed

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
