from __future__ import annotations

from wasm_build_test_support import *


class RuntimeObjectCacheTests(unittest.TestCase):
    def test_runtime_cache_llc_selection_prefers_configured_llvm_bindir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-llc-select-") as temporary:
            root = Path(temporary)
            configured = root / "selected-llvm" / "bin"
            on_path = root / "path-llvm" / "bin"
            configured.mkdir(parents=True)
            on_path.mkdir(parents=True)
            selected_llc = configured / "llc"
            path_llc = on_path / "llc"
            selected_llc.write_bytes(b"selected llc")
            selected_llc.chmod(0o755)
            path_llc.write_bytes(b"path llc")
            path_llc.chmod(0o755)

            with patch.dict(
                os.environ,
                {"ELISA_LLVM_BIN_DIR": str(configured), "PATH": str(on_path)},
                clear=True,
            ):
                self.assertEqual(
                    _resolve_llc_executable(),
                    selected_llc.resolve(),
                    "the runtime cache must fingerprint the compiler-selected llc before PATH",
                )

    def test_runtime_cache_hashes_delegated_compiler_overrides(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-delegated-compiler-") as temporary:
            root = Path(temporary)
            wrapper = root / "compiler-wrapper"
            wrapper.write_bytes(b"wrapper")
            wrapper.chmod(0o755)
            stage1 = root / "bin" / "elisac-stage1"
            stage1.parent.mkdir()
            stage1.write_bytes(b"stage1")
            stage1.chmod(0o755)
            selected = root / "selected-compiler"
            selected.write_bytes(b"compiler-a")
            selected.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            for selector in ("ELISA_STAGE1_BIN", "ELISA_STAGE1_SELF", "ELISA_S0_REAL", "ELISACORE_BIN"):
                with self.subTest(selector=selector):
                    def key() -> Path:
                        with (
                            patch.dict(
                                os.environ,
                                {selector: str(selected), "ELISA_Z3": str(solver)},
                                clear=True,
                            ),
                            patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                            patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                            patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                        ):
                            return runtime_cache_path(
                                root,
                                wrapper,
                                "wasm32-test",
                                runtime_source,
                                python_reference_scanner=True,
                            )

                    first = key()
                    before = selected.stat()
                    selected.write_bytes(b"compiler-b")
                    os.utime(selected, ns=(before.st_atime_ns, before.st_mtime_ns))
                    self.assertNotEqual(
                        first,
                        key(),
                        f"same-path {selector} replacement reused the WASM runtime key",
                    )
                    before = selected.stat()
                    selected.write_bytes(b"compiler-a")
                    os.utime(selected, ns=(before.st_atime_ns, before.st_mtime_ns))

    def test_runtime_cache_key_hashes_compiler_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-key-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler-a")
            compiler.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver-a")
            solver.chmod(0o755)
            llc = root / "llc"
            llc.write_bytes(b"llc-a")
            llc.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            def key() -> Path:
                with (
                    patch.dict(os.environ, {"ELISA_Z3": str(solver)}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=llc.resolve()),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            first = key()
            before = compiler.stat()
            compiler.write_bytes(b"compiler-b")
            os.utime(compiler, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(first, key(), "same-path compiler replacement reused the WASM runtime key")

            compiler.write_bytes(b"compiler-a")
            os.utime(compiler, ns=(before.st_atime_ns, before.st_mtime_ns))
            after_compiler_reset = key()
            before = solver.stat()
            solver.write_bytes(b"solver-b")
            os.utime(solver, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(
                after_compiler_reset,
                key(),
                "same-path SMT solver replacement reused the WASM runtime key",
            )

            solver.write_bytes(b"solver-a")
            os.utime(solver, ns=(before.st_atime_ns, before.st_mtime_ns))
            after_solver_reset = key()
            before = llc.stat()
            llc.write_bytes(b"llc-b")
            os.utime(llc, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(
                after_solver_reset,
                key(),
                "same-path llc replacement reused the WASM runtime key",
            )

            before_permission_change = key()
            compiler.chmod(0o644)
            self.assertNotEqual(
                before_permission_change,
                key(),
                "a non-executable compiler reused a runtime-object cache key",
            )

    def test_runtime_cache_key_hashes_native_object_merger(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-merger-key-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            stage1 = root / "bin" / "elisac-stage1"
            stage1.parent.mkdir()
            stage1.write_bytes(b"stage1")
            stage1.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)
            merger = root / "ld"
            merger.write_bytes(b"merger-a")
            merger.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            def key() -> Path:
                with (
                    patch.dict(
                        os.environ,
                        {"ELISA_Z3": str(solver), "ELISA_LD": str(merger)},
                        clear=True,
                    ),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            first = key()
            before = merger.stat()
            merger.write_bytes(b"merger-b")
            os.utime(merger, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertNotEqual(
                first,
                key(),
                "same-path object-merger replacement reused the WASM runtime key",
            )

    def test_darwin_merger_timeout_is_not_treated_as_the_system_linker(self) -> None:
        with (
            patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True),
            patch("scripts.wasm_build.sys.platform", "darwin"),
            patch("scripts.wasm_build.shutil.which", return_value="/usr/bin/ld"),
            patch(
                "scripts.wasm_build._resolve_executable",
                side_effect=lambda path: Path("/usr/bin/xcrun") if str(path) == "/usr/bin/xcrun" else None,
            ),
            patch(
                "scripts.wasm_build.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="xcrun --find ld", timeout=2),
            ),
        ):
            self.assertEqual(
                _resolve_native_object_merger(),
                (None, False),
                "a timed-out toolchain lookup must be marked unresolved rather than hashing /usr/bin/ld",
            )

    def test_runtime_cache_does_not_assume_path_z3_is_compiler_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-default-solver-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            tools = root / "tools"
            tools.mkdir()
            (tools / "z3").write_bytes(b"path-z3")
            runtime_source = root / "runtime.elisa"

            def key() -> Path:
                with (
                    patch.dict(os.environ, {"PATH": str(tools)}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            self.assertNotEqual(
                key(),
                key(),
                "an unresolved compiler-default SMT solver reused the PATH z3 key",
            )

    def test_runtime_cache_key_frames_source_path_and_flattened_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-key-frame-") as temporary:
            root = Path(temporary)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)

            def key(source_name: str, flattened: str) -> Path:
                with (
                    patch.dict(os.environ, {"ELISA_Z3": str(solver)}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value=flattened),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        root / source_name,
                        python_reference_scanner=True,
                    )

            first = key("a", "bc")
            second = key("ab", "c")
            self.assertNotEqual(
                first,
                second,
                "ambiguous runtime-path/source concatenation reused one cache key",
            )

    def test_runtime_cache_keys_effective_wasm_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-effective-mode-") as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            stage1 = root / "bin" / "elisac-stage1"
            stage1.write_bytes(b"stage1")
            stage1.chmod(0o755)
            compiler = root / "compiler"
            compiler.write_bytes(b"compiler")
            compiler.chmod(0o755)
            solver = root / "z3"
            solver.write_bytes(b"solver")
            solver.chmod(0o755)
            runtime_source = root / "runtime.elisa"

            def key(overrides: dict[str, str]) -> Path:
                with (
                    patch.dict(os.environ, {"ELISA_Z3": str(solver), **overrides}, clear=True),
                    patch("scripts.wasm_build.read_flat_source", return_value="flattened"),
                    patch("scripts.wasm_build._llvm_shared_libraries", return_value=[]),
                    patch("scripts.wasm_build._resolve_llc_executable", return_value=None),
                ):
                    return runtime_cache_path(
                        root,
                        compiler,
                        "wasm32-test",
                        runtime_source,
                        python_reference_scanner=True,
                    )

            self.assertEqual(
                key({"ELISA_STAGE1_WASM": "0"}),
                key({}),
                "the wrapper key used an inherited WASM mode it overrides before compilation",
            )

    @unittest.skipIf(os.name == "nt", "Windows ACL trust is not represented by POSIX mode bits")
    def test_runtime_cache_bypasses_writable_ancestor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-root-") as temporary:
            root = Path(temporary) / "shared" / "project"
            root.mkdir(parents=True)
            root.parent.chmod(0o777)
            workspace = root / "workspace"
            workspace.mkdir()
            cached = root / "build" / "wasm-cache" / "runtime.o"
            self.assertFalse(_runtime_cache_directory_ready(cached.parent, root, create=True))

            candidate = workspace / "runtime-cache-candidate.o"

            def compile_candidate(*_args: object) -> None:
                candidate.write_bytes(b"fresh-object")

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=compile_candidate),
                patch(
                    "scripts.wasm_build._publish_runtime_cache",
                    side_effect=AssertionError("untrusted root published an object"),
                ),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")

    def test_runtime_cache_entry_rejects_truncated_and_symlink_payloads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-entry-") as temporary:
            root = Path(temporary)
            cache_dir = root / "build" / "wasm-cache"
            cache_dir.mkdir(parents=True)
            candidate = root / "candidate.o"
            cached = cache_dir / "runtime.o"
            candidate.write_bytes(b"verified-object")
            self.assertTrue(_publish_runtime_cache(candidate, cached))
            self.assertTrue(_runtime_cache_entry_valid(cached))

            cached.write_bytes(b"truncated")
            self.assertFalse(_runtime_cache_entry_valid(cached))

            cached.unlink()
            cached.with_suffix(".o.json").unlink()
            target = root / "outside.o"
            target.write_bytes(b"outside-object")
            cached.symlink_to(target)
            self.assertFalse(_runtime_cache_entry_valid(cached))

    def test_runtime_cache_file_reads_are_nonblocking(self) -> None:
        nonblocking = getattr(os, "O_NONBLOCK", 0)
        if not nonblocking:
            self.skipTest("platform has no nonblocking file-open flag")
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-nonblocking-") as temporary:
            root = Path(temporary)
            cache_dir = root / "build" / "wasm-cache"
            cache_dir.mkdir(parents=True)
            candidate = root / "candidate.o"
            cached = cache_dir / "runtime.o"
            candidate.write_bytes(b"verified-object")
            real_open = os.open
            observed_flags: list[int] = []

            def record_cache_open(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
                if os.fspath(path) in {str(candidate), str(cached), str(cached) + ".json"}:
                    observed_flags.append(flags)
                return real_open(path, flags, *args, **kwargs)

            with patch("scripts.wasm_build.os.open", side_effect=record_cache_open):
                self.assertTrue(_publish_runtime_cache(candidate, cached))
                self.assertTrue(_runtime_cache_entry_valid(cached))

            self.assertGreaterEqual(len(observed_flags), 4)
            self.assertTrue(all(flags & nonblocking for flags in observed_flags))

    def test_failed_manifest_validation_keeps_fresh_candidate_usable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-publish-") as temporary:
            root = Path(temporary)
            cache_dir = root / "build" / "wasm-cache"
            cached = cache_dir / "runtime.o"
            workspace = root / "workspace"
            workspace.mkdir()
            candidate = workspace / "runtime-cache-candidate.o"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=lambda *_args: candidate.write_bytes(b"fresh-object")),
                patch("scripts.wasm_build._runtime_cache_entry_valid", return_value=False),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")

    def test_runtime_cache_hit_rechecks_current_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-hit-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            cache_dir = root / "build" / "wasm-cache"
            cache_dir.mkdir(parents=True)
            cached = cache_dir / "runtime.o"
            original = workspace / "original.o"
            original.write_bytes(b"cached-object")
            self.assertTrue(_publish_runtime_cache(original, cached))

            identity_checks = 0

            def identity_changed() -> bool:
                nonlocal identity_checks
                identity_checks += 1
                return False

            candidate = workspace / "candidate.o"

            def compile_candidate(*_args: object) -> None:
                candidate.write_bytes(b"fresh-object")

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._runtime_cache_directory_ready", return_value=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=compile_candidate),
                patch(
                    "scripts.wasm_build._publish_runtime_cache",
                    side_effect=AssertionError("changed identity was published"),
                ),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                    identity_is_current=identity_changed,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")
            self.assertEqual(identity_checks, 2)

    def test_runtime_cache_bypasses_preload_and_observer_requests(self) -> None:
        for variable, value in (
            ("LD_PRELOAD", "/tmp/requested-side-effect"),
            ("DYLD_INSERT_LIBRARIES", "/tmp/requested-side-effect"),
            ("ELISA_SMT_RLIMIT_LOG", "/tmp/requested-side-effect"),
            ("ELISACORE_CACHE_DEBUG", "/tmp/requested-side-effect"),
            ("ELISACORE_DUMP_MODULE_ON_VERIFY_FAILURE", "/tmp/requested-side-effect"),
            ("ELISACORE_RETAINED_SERVER", ""),
            ("ELISACORE_RETAINED_PROFILE_DIR", "/tmp/requested-side-effect"),
            ("ELISACORE_RETAINED_HEAPPROFILE", "/tmp/requested-side-effect"),
            ("ELISACORE_RETAINED_FAST_PREPARE", "shadow"),
        ):
            with self.subTest(variable=variable), tempfile.TemporaryDirectory(prefix="wasm-runtime-bypass-") as temporary:
                root = Path(temporary)
                workspace = root / "workspace"
                workspace.mkdir()
                candidate = workspace / "runtime-cache-candidate.o"
                cached = root / "build" / "wasm-cache" / "runtime.o"

                def compile_candidate(*_args: object) -> None:
                    candidate.write_bytes(b"fresh-object")

                with (
                    patch.dict(os.environ, {variable: value}, clear=True),
                    patch("scripts.wasm_build._compile_runtime_object", side_effect=compile_candidate),
                    patch(
                        "scripts.wasm_build._publish_runtime_cache",
                        side_effect=AssertionError("observer request used cache"),
                    ),
                ):
                    result = _runtime_object_from_cache(
                        cached,
                        root,
                        workspace,
                        "unused-compiler",
                        "wasm32-test",
                        root / "runtime.elisa",
                        {},
                        label="test runtime compilation",
                        candidate_name=candidate.name,
                    )
                self.assertEqual(result, candidate)
                self.assertEqual(result.read_bytes(), b"fresh-object")

    def test_runtime_cache_keeps_fast_prepare_on_cacheable(self) -> None:
        with patch.dict(os.environ, {"ELISACORE_RETAINED_FAST_PREPARE": "on"}, clear=True):
            self.assertFalse(_runtime_cache_observer_requested())

    def test_runtime_identity_drift_keeps_candidate_out_of_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wasm-runtime-drift-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            candidate = workspace / "runtime-cache-candidate.o"
            cached = root / "build" / "wasm-cache" / "runtime.o"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("scripts.wasm_build._compile_runtime_object", side_effect=lambda *_args: candidate.write_bytes(b"fresh-object")),
                patch("scripts.wasm_build._publish_runtime_cache", side_effect=AssertionError("changed identity was published")),
            ):
                result = _runtime_object_from_cache(
                    cached,
                    root,
                    workspace,
                    "unused-compiler",
                    "wasm32-test",
                    root / "runtime.elisa",
                    {},
                    label="test runtime compilation",
                    candidate_name=candidate.name,
                    identity_is_current=lambda: False,
                )
            self.assertEqual(result, candidate)
            self.assertEqual(result.read_bytes(), b"fresh-object")

