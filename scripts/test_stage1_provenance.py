"""Stage1 product provenance must notice source, build-recipe, and binary changes."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import stage1_provenance


original_revision = stage1_provenance.source_revision
original_toolchain_fingerprint = stage1_provenance.llvm_toolchain_fingerprint
stage1_provenance.source_revision = lambda _root: "test-revision"
# This unit isolates source/recipe/product freshness from the host toolchain. Production
# Stage1 provenance requires LLVM_CONFIG and records its selected backend separately.
stage1_provenance.llvm_toolchain_fingerprint = lambda _previous=None, exact=False: None


def place_product_after_sources(root, product):
    newest_source_mtime_ns = max(
        path.stat().st_mtime_ns
        for directory in stage1_provenance.SOURCE_DIRS
        for path in (root / directory).rglob("*")
        if path.is_file() and path.suffix in (".elisa", ".elisai")
    )
    product_stat = product.stat()
    os.utime(
        product,
        ns=(product_stat.st_atime_ns, max(product_stat.st_mtime_ns, newest_source_mtime_ns) + 1_000_000_000),
    )


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    for name in stage1_provenance.SOURCE_DIRS:
        (root / name).mkdir(parents=True)
        (root / name / "unit.elisa").write_text("module Unit:\n    pass\n")
    for name in stage1_provenance.BUILD_RECIPES:
        recipe = root / name
        recipe.parent.mkdir(parents=True, exist_ok=True)
        recipe.write_text("build recipe\n")
    product = root / "bin" / "elisac-stage1"
    product.parent.mkdir()
    product.write_bytes(b"stage1 product")

    seed_inputs = stage1_provenance.input_fingerprint(root)
    assert stage1_provenance.check_inputs(root, seed_inputs) == 0
    place_product_after_sources(root, product)
    stage1_provenance.record(root, product, seed_inputs)
    with patch.object(stage1_provenance, "digest_files", side_effect=AssertionError("fast check read source contents")), \
         patch.object(stage1_provenance, "sha256_file", side_effect=AssertionError("fast check rehashed product")):
        assert stage1_provenance.check(root, product) == 0

    source = root / "src" / "unit.elisa"
    source_bytes = source.read_bytes()
    source_stat = source.stat()
    os.utime(source, ns=(source_stat.st_atime_ns, product.stat().st_mtime_ns + 2_000_000_000))
    assert source.read_bytes() == source_bytes
    stale_stderr = io.StringIO()
    with contextlib.redirect_stderr(stale_stderr):
        assert stage1_provenance.check(root, product) == 2
    assert f"{source.relative_to(root).as_posix()} is newer than {product.resolve()}" in stale_stderr.getvalue()
    os.utime(source, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
    assert stage1_provenance.check(root, product) == 0

    manifest_path = stage1_provenance.manifest_path(product)
    manifest = json.loads(manifest_path.read_text())
    manifest["schema"] = "elisa-stage1-provenance-v3"
    manifest.pop("seed_configuration", None)
    manifest_path.write_text(json.dumps(manifest))
    assert stage1_provenance.check(root, product) == 2
    stage1_provenance.record(root, product)

    (root / "src" / "unit.elisa").write_text("module Unit:\n    def changed() -> i64: return 1\n")
    assert stage1_provenance.check_inputs(root, seed_inputs) == 2
    try:
        stage1_provenance.record(root, product, seed_inputs)
    except RuntimeError as error:
        assert "changed during seed" in str(error)
    else:
        raise AssertionError("record accepted sources that changed during seed")
    assert stage1_provenance.check(root, product) == 2

    (root / "src" / "unit.elisa").write_text("module Unit:\n    pass\n")
    (root / "scripts" / "elisac_stage1_seed.sh").write_text("changed build recipe\n")
    assert stage1_provenance.check(root, product) == 2

    (root / "scripts" / "elisac_stage1_seed.sh").write_text("build recipe\n")
    product.write_bytes(b"replaced product")
    assert stage1_provenance.check(root, product) == 2

stage1_provenance.source_revision = original_revision
stage1_provenance.llvm_toolchain_fingerprint = original_toolchain_fingerprint

# Toolchain file digests may be reused only while the full local file identity is stable.
# In particular, preserve mtime while rewriting a same-size library to model package tools
# that replace bytes while retaining the visible timestamp.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    bindir = root / "bin"
    libdir = root / "lib"
    custom_libdir = root / "custom-lib"
    bindir.mkdir()
    libdir.mkdir()
    custom_libdir.mkdir()
    library = libdir / "libLLVM-test.dylib"
    library.write_bytes(b"llvm-test-library-v1")
    custom_library = custom_libdir / ("libLLVM.dylib" if sys.platform == "darwin" else "libLLVM.so")
    custom_library.write_bytes(b"custom-llvm-library-v1")
    clang = bindir / "clang"
    clang.write_text(f"#!{sys.executable}\nprint('clang version test')\n")
    clang.chmod(0o755)
    llvm_config = bindir / "llvm-config"
    llvm_config.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if args == ['--version']:\n"
        "    print('23.1.3')\n"
        "elif args == ['--bindir']:\n"
        f"    print({str(bindir)!r})\n"
        "elif args == ['--libdir']:\n"
        f"    print({str(libdir)!r})\n"
        "elif args == ['--link-shared', '--libfiles']:\n"
        f"    print({str(library)!r})\n"
        "else:\n"
        "    raise SystemExit(2)\n"
    )
    llvm_config.chmod(0o755)
    bootstrap_runtime = root / "bootstrap-runtime.o"
    bootstrap_runtime.write_bytes(b"bootstrap runtime object")
    toolchain_env = {
        "LLVM_CONFIG": str(llvm_config),
        "ELISA_LLVM_BIN_DIR": str(bindir),
        "ELISA_LLVM_LIBDIR": str(libdir),
        "ELISA_CLANG": str(clang),
        "ELISA_LLVM_LIBS": f"-L{custom_libdir} -lLLVM",
        "ELISA_STAGE1_SEED_STAGE0_BIN": str(clang),
        "ELISA_STAGE1_SEED_CLANG": str(clang),
        "ELISA_STAGE1_SEED_OPT_LEVEL": "-O2",
        "ELISA_STAGE1_SEED_RUNTIME_OBJ": str(bootstrap_runtime),
        "ELISA_STAGE1_SEED_RUNTIME_SHA256": hashlib.sha256(bootstrap_runtime.read_bytes()).hexdigest(),
        "ELISA_LINK_EXE_FLAGS": "-Wl,test-executable",
        "ELISA_LD_DEAD_STRIP": "-Wl,test-dead-strip",
        "ELISA_LD_STACK_512M": "-Wl,test-stack",
    }
    with patch.dict(os.environ, toolchain_env):
        original = stage1_provenance.llvm_toolchain_fingerprint()
        assert [item["path"] for item in original["link_libraries"]] == [str(custom_library.resolve())]
        with patch.object(stage1_provenance, "sha256_file", side_effect=AssertionError("unchanged artifact was rehashed")):
            unchanged = stage1_provenance.llvm_toolchain_fingerprint(original)
        assert unchanged == original

        custom_before = custom_library.stat()
        custom_library.write_bytes(b"custom-llvm-library-v2")
        os.utime(custom_library, ns=(custom_before.st_atime_ns, custom_before.st_mtime_ns))
        custom_after = custom_library.stat()
        assert custom_after.st_size == custom_before.st_size
        assert custom_after.st_mtime_ns == custom_before.st_mtime_ns
        assert custom_after.st_ctime_ns != custom_before.st_ctime_ns
        custom_changed = stage1_provenance.llvm_toolchain_fingerprint(original)
        assert custom_changed["link_libraries"][0]["sha256"] != original["link_libraries"][0]["sha256"]

        before = library.stat()
        library.write_bytes(b"llvm-test-library-v2")
        os.utime(library, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = library.stat()
        assert after.st_size == before.st_size
        assert after.st_mtime_ns == before.st_mtime_ns
        assert after.st_ctime_ns != before.st_ctime_ns
        changed = stage1_provenance.llvm_toolchain_fingerprint(original)
        assert changed["dynamic_libraries"][0]["sha256"] != original["dynamic_libraries"][0]["sha256"]

        damaged_previous = json.loads(json.dumps(changed))
        damaged_previous["dynamic_libraries"][0]["sha256"] = "not-a-sha256"
        repaired = stage1_provenance.llvm_toolchain_fingerprint(damaged_previous)
        assert repaired["dynamic_libraries"][0]["sha256"] == hashlib.sha256(library.read_bytes()).hexdigest()

        forged_previous = json.loads(json.dumps(changed))
        forged_previous["dynamic_libraries"][0]["sha256"] = "0" * 64
        exact = stage1_provenance.llvm_toolchain_fingerprint(forged_previous, exact=True)
        assert exact["dynamic_libraries"][0]["sha256"] == hashlib.sha256(library.read_bytes()).hexdigest()

        with patch.object(stage1_provenance, "source_revision", lambda _root: "test-toolchain-revision"):
            project = root / "project"
            for name in stage1_provenance.SOURCE_DIRS:
                source = project / name / "unit.elisa"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("module Unit:\n    pass\n")
            for name in stage1_provenance.BUILD_RECIPES:
                recipe = project / name
                recipe.parent.mkdir(parents=True, exist_ok=True)
                recipe.write_text("build recipe\n")
            product = project / "bin" / "elisac-stage1"
            product.parent.mkdir(parents=True)
            product.write_bytes(b"stage1 product")
            expected = stage1_provenance.input_fingerprint(project)
            assert expected["seed_configuration"]["optimization_level"] == "-O2"
            assert expected["seed_configuration"]["bootstrap_kind"] == "stage0"
            assert expected["seed_configuration"]["bootstrap_runtime_link_mode"] == "static-object"
            assert expected["seed_configuration"]["executable_link_flags"] == "-Wl,test-executable"
            renamed_stage1 = bindir / "renamed-bootstrap"
            renamed_stage1.write_bytes(b"renamed stage1 compiler")
            renamed_stage1.chmod(0o755)
            stage1_provenance.manifest_path(renamed_stage1).write_text(
                json.dumps({
                    "schema": stage1_provenance.SCHEMA,
                    "product_sha256": hashlib.sha256(renamed_stage1.read_bytes()).hexdigest(),
                })
            )
            with patch.dict(os.environ, {
                "ELISA_STAGE1_SEED_BOOTSTRAP_BIN": str(renamed_stage1),
                "ELISA_STAGE1_SEED_BOOTSTRAP_KIND": "",
            }):
                renamed_seed = stage1_provenance.seed_configuration_fingerprint(
                    expected["seed_configuration"], exact=True
                )
            assert renamed_seed["bootstrap_kind"] == "stage1"
            assert renamed_seed["bootstrap_compiler"]["path"] == str(renamed_stage1.resolve())
            with patch.dict(os.environ, {"ELISA_STAGE1_SEED_OPT_LEVEL": "-O3"}):
                changed_seed = stage1_provenance.seed_configuration_fingerprint(
                    expected["seed_configuration"], exact=True
                )
                assert changed_seed["optimization_level"] == "-O3"
            stage1_provenance.record(project, product, expected)
            manifest_path = stage1_provenance.manifest_path(product)
            manifest = json.loads(manifest_path.read_text())
            manifest["llvm_toolchain"]["dynamic_libraries"][0]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest))
            assert stage1_provenance.check(project, product, exact=True) == 2

print("stage1 provenance: exact source, recipe and product fingerprints verified")
