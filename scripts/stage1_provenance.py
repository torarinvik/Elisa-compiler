#!/usr/bin/env python3
"""Record and verify the exact source inputs behind a local Stage1 product."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


SCHEMA = "elisa-stage1-provenance-v4"
SOURCE_DIRS = ("src", "elisacore_std")
BUILD_RECIPES = (
    "scripts/platform.sh",
    "scripts/elisac_stage1.sh",
    "scripts/stage1_object_cache.py",
    "scripts/elisac_stage1_seed.sh",
    "scripts/assert_stage0_fresh.sh",
    "scripts/assert_stage1_fresh.sh",
    "scripts/process_rss.sh",
    "scripts/build_runtime_object.sh",
    "scripts/write_profiler_hook_fallbacks.sh",
    "scripts/stage1_provenance.py",
)


def digest_files(root, paths):
    digest = hashlib.sha256()
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
        elif path.is_file():
            files.append(path)
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def file_stat_identity(path):
    stat = Path(path).stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }


def stat_inventory_digest(root, paths, freshness_extensions=()):
    root = Path(root).resolve()
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
        elif path.is_file():
            files.append(path)
    digest = hashlib.sha256()
    newest_source_mtime_ns = None
    newest_source_path = None
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        identity = file_stat_identity(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("ascii"))
        digest.update(b"\0")
        # Preserve the former `find ... -newer BIN` freshness rule while collecting it
        # during this inventory pass. `find -type f` does not follow file symlinks.
        if freshness_extensions and path.suffix in freshness_extensions and not path.is_symlink():
            mtime_ns = identity["mtime_ns"]
            if newest_source_mtime_ns is None or mtime_ns > newest_source_mtime_ns:
                newest_source_mtime_ns = mtime_ns
                newest_source_path = relative
    return digest.hexdigest(), newest_source_mtime_ns, newest_source_path


def valid_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def bootstrap_compiler_kind(path):
    """Identify Stage1 products by their recorded product hash, not only their filename."""
    path = Path(path).expanduser().resolve()
    explicit = os.environ.get("ELISA_STAGE1_SEED_BOOTSTRAP_KIND")
    if explicit:
        if explicit not in ("stage0", "stage1"):
            raise RuntimeError(
                "ELISA_STAGE1_SEED_BOOTSTRAP_KIND must be stage0 or stage1 "
                f"(got {explicit!r})"
            )
        return explicit
    if path.name == "elisac-stage1":
        return "stage1"
    try:
        recorded = json.loads(manifest_path(path).read_text())
        if (
            isinstance(recorded, dict)
            and isinstance(recorded.get("schema"), str)
            and recorded["schema"].startswith("elisa-stage1-provenance-")
            and recorded.get("product_sha256") == sha256_file(path)
        ):
            return "stage1"
    except (OSError, json.JSONDecodeError):
        pass
    # The normal Stage0 product is named `elisac`. Keep legacy custom Stage0 paths working;
    # callers with a renamed compiler of ambiguous origin can set the explicit kind above.
    return "stage0"


def toolchain_content_view(value):
    if isinstance(value, dict):
        stat_fields = {"size", "mtime_ns", "ctime_ns", "device", "inode"}
        return {
            key: toolchain_content_view(item)
            for key, item in value.items()
            if key not in stat_fields
        }
    if isinstance(value, list):
        return [toolchain_content_view(item) for item in value]
    return value


def seed_configuration_fingerprint(previous=None, exact=False):
    previous = previous if isinstance(previous, dict) else {}
    previous_bootstrap = previous.get("bootstrap_compiler")
    previous_runtime = previous.get("bootstrap_runtime_object")
    bootstrap_path = (
        os.environ.get("ELISA_STAGE1_SEED_BOOTSTRAP_BIN")
        or os.environ.get("ELISA_STAGE1_SEED_STAGE0_BIN")
        or os.environ.get("BOOTSTRAP_BIN")
        or os.environ.get("STAGE0_BIN")
        or os.environ.get("ELISACORE_BIN")
    )
    rebuilding = bool(bootstrap_path)
    if rebuilding:
        bootstrap_path = Path(bootstrap_path).expanduser().resolve()
        if not bootstrap_path.is_file() or not os.access(bootstrap_path, os.X_OK):
            raise RuntimeError(f"bootstrap compiler is not executable: {bootstrap_path}")
        bootstrap_kind = bootstrap_compiler_kind(bootstrap_path)
        bootstrap = fingerprint_artifact(
            bootstrap_path,
            previous_bootstrap,
            exact=exact,
            description=f"{bootstrap_kind.title()} bootstrap compiler",
        )
        optimization_level = os.environ.get("ELISA_STAGE1_SEED_OPT_LEVEL", "-O3")
        runtime_path = os.environ.get("ELISA_STAGE1_SEED_RUNTIME_OBJ", "")
        expected_runtime_sha = os.environ.get("ELISA_STAGE1_SEED_RUNTIME_SHA256", "")
        if optimization_level not in ("-O0", "-O1", "-O2", "-O3"):
            raise RuntimeError(f"invalid ELISA_STAGE1_SEED_OPT_LEVEL: {optimization_level}")
        if runtime_path:
            runtime_path = Path(runtime_path).expanduser().resolve()
            if not runtime_path.is_file() or not os.access(runtime_path, os.R_OK):
                raise RuntimeError(f"bootstrap runtime object is not readable: {runtime_path}")
            if not valid_sha256(expected_runtime_sha):
                raise RuntimeError("ELISA_STAGE1_SEED_RUNTIME_SHA256 must be a lowercase SHA-256")
            runtime_artifact = fingerprint_artifact(
                runtime_path,
                previous_runtime,
                exact=exact,
                description="bootstrap runtime object",
            )
            if runtime_artifact["sha256"] != expected_runtime_sha:
                raise RuntimeError(f"bootstrap runtime SHA-256 mismatch: {runtime_path}")
        else:
            if expected_runtime_sha:
                raise RuntimeError("ELISA_STAGE1_SEED_RUNTIME_SHA256 was set without a runtime object")
            runtime_artifact = None
        host_os = os.uname().sysname
        if host_os == "Linux":
            seed_link_flags = ["-no-pie", "-Wl,--gc-sections"]
            profiler_hook_mode = "--host-callbacks"
        elif host_os == "Darwin":
            seed_link_flags = ["-Wl,-dead_strip", "-Wl,-stack_size,0x20000000"]
            profiler_hook_mode = ""
        else:
            raise RuntimeError(f"unsupported Stage1 seed host OS: {host_os}")
        clang_path = (
            os.environ.get("ELISA_STAGE1_SEED_CLANG")
            or os.environ.get("ELISA_CLANG")
            or ""
        )
        return {
            "bootstrap_compiler": bootstrap,
            "bootstrap_kind": bootstrap_kind,
            "optimization_level": optimization_level,
            "bootstrap_runtime_object": runtime_artifact,
            "bootstrap_runtime_expected_sha256": expected_runtime_sha or None,
            "bootstrap_runtime_link_mode": "static-object" if runtime_artifact else "none",
            "host_os": host_os,
            "elisa_host_os": os.environ.get("ELISA_HOST_OS") or host_os,
            "seed_link_flags": seed_link_flags,
            "executable_link_flags": os.environ.get("ELISA_LINK_EXE_FLAGS", ""),
            "dead_strip_flags": os.environ.get("ELISA_LD_DEAD_STRIP", ""),
            "stack_flags": os.environ.get("ELISA_LD_STACK_512M", ""),
            "llvm_link_flags": os.environ.get("ELISA_LLVM_LIBS", ""),
            "profiler_hook_mode": profiler_hook_mode,
            "clang_path": str(Path(clang_path).expanduser().resolve()) if clang_path else None,
        }
    if not previous:
        return None
    bootstrap = previous_bootstrap
    if not isinstance(bootstrap, dict) or not isinstance(bootstrap.get("path"), str):
        raise RuntimeError("Stage1 provenance is missing its bootstrap compiler identity")
    recorded_kind = previous.get("bootstrap_kind")
    bootstrap_description = (
        f"recorded {recorded_kind.title()} bootstrap compiler"
        if recorded_kind in ("stage0", "stage1")
        else "recorded bootstrap compiler"
    )
    current_bootstrap = fingerprint_artifact(
        bootstrap["path"], bootstrap, exact=exact, description=bootstrap_description
    )
    runtime_artifact = None
    if previous_runtime is not None:
        if not isinstance(previous_runtime, dict) or not isinstance(previous_runtime.get("path"), str):
            raise RuntimeError("Stage1 provenance has an invalid bootstrap runtime identity")
        runtime_artifact = fingerprint_artifact(
            previous_runtime["path"], previous_runtime, exact=exact, description="recorded bootstrap runtime object"
        )
        expected_runtime_sha = previous.get("bootstrap_runtime_expected_sha256")
        if expected_runtime_sha and runtime_artifact["sha256"] != expected_runtime_sha:
            raise RuntimeError(f"recorded bootstrap runtime SHA-256 mismatch: {previous_runtime['path']}")
    return {
        **previous,
        "bootstrap_compiler": current_bootstrap,
        "bootstrap_runtime_object": runtime_artifact,
    }


def source_revision(root):
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    snapshot = root / "SNAPSHOT"
    if snapshot.is_file():
        for line in snapshot.read_text().splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() == "source_revision" and value.strip():
                return value.strip()
    raise RuntimeError(f"cannot read Stage1 source revision from {root}")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_artifact(path, previous=None, exact=False, description="artifact"):
    path = Path(path).resolve()
    try:
        identity = file_stat_identity(path)
    except OSError as error:
        raise RuntimeError(f"could not stat {description} {path}: {error}") from error
    previous = previous if isinstance(previous, dict) else {}
    prior_digest = previous.get("sha256")
    reusable = (
        not exact
        and all(previous.get(key) == value for key, value in identity.items())
        and valid_sha256(prior_digest)
    )
    if reusable:
        digest = prior_digest
    else:
        digest = sha256_file(path)
        try:
            after_identity = file_stat_identity(path)
        except OSError as error:
            raise RuntimeError(f"could not restat {description} {path}: {error}") from error
        if after_identity != identity:
            raise RuntimeError(f"{description} changed while fingerprinting: {path}")
    return {"path": str(path), **identity, "sha256": digest}


def llvm_toolchain_fingerprint(previous=None, exact=False):
    previous = previous if isinstance(previous, dict) else {}
    raw_config = os.environ.get("LLVM_CONFIG") or previous.get("llvm_config_path")
    if not raw_config:
        raise RuntimeError("LLVM_CONFIG is required to fingerprint Stage1; source scripts/platform.sh first")
    previous_artifacts = {}
    for key in ("llvm_config_artifact", "clang_artifact"):
        artifact = previous.get(key)
        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
            previous_artifacts[artifact["path"]] = artifact
    for key in ("dynamic_libraries", "static_archives", "link_libraries"):
        artifacts = previous.get(key)
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                    previous_artifacts[artifact["path"]] = artifact

    def artifact_record(path):
        path = Path(path).resolve()
        return fingerprint_artifact(
            path,
            previous_artifacts.get(str(path)),
            exact=exact,
            description="LLVM toolchain input",
        )

    def artifact_unchanged(prior, current):
        return (
            isinstance(prior, dict)
            and prior.get("path") == current["path"]
            and all(prior.get(key) == current[key] for key in ("size", "mtime_ns", "ctime_ns", "device", "inode"))
            and prior.get("sha256") == current["sha256"]
            and isinstance(prior.get("sha256"), str)
            and len(prior["sha256"]) == 64
            and all(character in "0123456789abcdef" for character in prior["sha256"])
        )

    config = shutil.which(raw_config) or raw_config
    config = Path(config).resolve()
    if not config.is_file() or not os.access(config, os.X_OK):
        raise RuntimeError(f"LLVM_CONFIG is not an executable file: {config}")
    config_artifact = artifact_record(config)
    config_unchanged = artifact_unchanged(previous.get("llvm_config_artifact"), config_artifact)

    def llvm_config(*arguments):
        try:
            result = subprocess.run(
                [str(config), *arguments], capture_output=True, text=True, check=True
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"could not query {config} {' '.join(arguments)}: {error}") from error
        return result.stdout.strip()

    def resolved_directory(raw, description):
        path = Path(raw).resolve()
        if not path.is_dir():
            raise RuntimeError(f"LLVM toolchain {description} is not a directory: {path}")
        return str(path)

    version = previous.get("llvm_version") if config_unchanged else None
    if not version:
        version = llvm_config("--version")
    raw_bindir = os.environ.get("ELISA_LLVM_BIN_DIR")
    if not raw_bindir:
        raw_bindir = previous.get("llvm_bindir") if config_unchanged else None
    bindir = resolved_directory(raw_bindir or llvm_config("--bindir"), "bin directory")
    raw_libdir = os.environ.get("ELISA_LLVM_LIBDIR")
    if not raw_libdir:
        raw_libdir = previous.get("llvm_libdir") if config_unchanged else None
    libdir = resolved_directory(raw_libdir or llvm_config("--libdir"), "library directory")
    raw_clang = (
        os.environ.get("ELISA_CLANG")
        or os.environ.get("ELISA_STAGE1_SEED_CLANG")
        or (previous.get("clang_path") if config_unchanged else None)
    )
    if not raw_clang:
        selected_clang = Path(bindir) / "clang"
        raw_clang = str(selected_clang) if selected_clang.is_file() and os.access(selected_clang, os.X_OK) else None
    if not raw_clang or not os.access(shutil.which(raw_clang) or raw_clang, os.X_OK):
        raw_clang = shutil.which("clang")
    if not raw_clang:
        raise RuntimeError(f"selected LLVM toolchain has no executable clang in {bindir} or on PATH")
    clang = shutil.which(raw_clang) or raw_clang
    clang = Path(clang).resolve()
    if not clang.is_file() or not os.access(clang, os.X_OK):
        raise RuntimeError(f"selected LLVM clang is not executable: {clang}")
    clang_artifact = artifact_record(clang)
    clang_unchanged = artifact_unchanged(previous.get("clang_artifact"), clang_artifact)
    clang_version = previous.get("clang_version") if clang_unchanged else None
    if not clang_version:
        try:
            clang_result = subprocess.run([str(clang), "--version"], capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"could not query selected clang {clang}: {error}") from error
        clang_version = clang_result.stdout.splitlines()[0] if clang_result.stdout.splitlines() else ""
    if "ELISA_LLVM_LIBS" in os.environ:
        link_flags = os.environ["ELISA_LLVM_LIBS"]
    else:
        link_flags = previous.get("link_flags", "") if config_unchanged else ""
    link_tokens = shlex.split(link_flags)
    link_search_dirs = [Path(libdir)]
    llvm_library_names = []
    direct_link_libraries = []
    token_index = 0
    while token_index < len(link_tokens):
        token = link_tokens[token_index]
        if token == "-L" and token_index + 1 < len(link_tokens):
            link_search_dirs.append(Path(link_tokens[token_index + 1]))
            token_index += 2
            continue
        if token.startswith("-L") and len(token) > 2:
            link_search_dirs.append(Path(token[2:]))
        if token.startswith("-lLLVM"):
            llvm_library_names.append(token[2:])
        elif token.endswith((".dylib", ".so", ".a", ".lib")) or ".so." in token:
            candidate = Path(token)
            if candidate.is_file():
                direct_link_libraries.append(candidate.resolve())
        token_index += 1
    link_library_paths = set(direct_link_libraries)
    if sys.platform == "darwin":
        library_suffixes = (".dylib", ".tbd", ".a")
    else:
        library_suffixes = (".so", ".a")
    for library_name in llvm_library_names:
        if library_name.startswith(":"):
            candidate_names = [library_name[1:]]
        else:
            candidate_names = [f"lib{library_name}{suffix}" for suffix in library_suffixes]
            candidate_names.extend(f"lib{library_name}.so.*" for _ in (0,) if sys.platform != "darwin")
        for directory in link_search_dirs:
            for candidate_name in candidate_names:
                candidates = directory.glob(candidate_name)
                for candidate in candidates:
                    if candidate.is_file():
                        link_library_paths.add(candidate.resolve())
    link_libraries = [artifact_record(path) for path in sorted(link_library_paths)]
    static_link = any(
        "start-group" in token or "-Bstatic" in token or token in ("-static",)
        or token.endswith((".a", ".lib"))
        for token in link_tokens
    )
    dynamic_link = any(token == "-lLLVM" or token.startswith("-lLLVM-") for token in link_tokens)
    link_mode = "static" if static_link else ("dynamic" if dynamic_link else "unknown")
    if link_mode == "unknown":
        raise RuntimeError("ELISA_LLVM_LIBS does not identify whether Stage1 links LLVM statically or dynamically")
    static_archives = []
    dynamic_libraries = []
    reuse_link_inputs = (
        config_unchanged
        and previous.get("link_flags") == link_flags
        and previous.get("link_mode") == link_mode
    )
    if link_mode == "static":
        prior_archives = previous.get("static_archives") if reuse_link_inputs else None
        if isinstance(prior_archives, list) and prior_archives:
            archive_paths = sorted({item["path"] for item in prior_archives if isinstance(item, dict) and "path" in item})
        else:
            archive_tokens = shlex.split(llvm_config("--link-static", "--libfiles"))
            archive_tokens.extend(token for token in link_tokens if token.endswith((".a", ".lib")))
            archive_paths = sorted({str(Path(token).resolve()) for token in archive_tokens})
        if not archive_paths:
            raise RuntimeError(f"static LLVM link selected, but {config} reported no archive files")
        for raw_path in archive_paths:
            archive = Path(raw_path)
            if not archive.is_file():
                raise RuntimeError(f"static LLVM archive is missing: {archive}")
            static_archives.append(artifact_record(archive))
    elif link_mode == "dynamic":
        prior_libraries = previous.get("dynamic_libraries") if reuse_link_inputs else None
        if isinstance(prior_libraries, list) and prior_libraries:
            library_paths = sorted({item["path"] for item in prior_libraries if isinstance(item, dict) and "path" in item})
        else:
            library_tokens = shlex.split(llvm_config("--link-shared", "--libfiles"))
            library_paths = sorted({
                str(Path(token).resolve())
                for token in library_tokens
                if token.endswith((".dylib", ".so")) or ".so." in token
            })
        if not library_paths:
            raise RuntimeError(f"dynamic LLVM link selected, but {config} reported no shared LLVM library")
        for raw_path in library_paths:
            library = Path(raw_path)
            if not library.is_file():
                raise RuntimeError(f"dynamic LLVM library is missing: {library}")
            dynamic_libraries.append(artifact_record(library))

    return {
        "llvm_config_path": str(config),
        "llvm_config_artifact": config_artifact,
        "llvm_version": version,
        "llvm_bindir": bindir,
        "llvm_libdir": libdir,
        "clang_path": str(clang),
        "clang_artifact": clang_artifact,
        "clang_version": clang_version,
        "link_mode": link_mode,
        "link_flags": link_flags,
        "dynamic_libraries": dynamic_libraries,
        "static_archives": static_archives,
        "link_libraries": link_libraries,
    }


def input_fingerprint(
    root,
    previous_toolchain=None,
    exact_toolchain=False,
    previous_inputs=None,
    exact_content=True,
):
    root = Path(root).resolve()
    missing = [name for name in SOURCE_DIRS + BUILD_RECIPES if not (root / name).exists()]
    if missing:
        raise RuntimeError(f"Stage1 provenance inputs are missing: {', '.join(missing)}")
    previous_inputs = previous_inputs if isinstance(previous_inputs, dict) else {}
    source_paths = [root / name for name in SOURCE_DIRS]
    recipe_paths = [root / name for name in BUILD_RECIPES]
    source_stats, source_max_mtime_ns, source_max_mtime_path = stat_inventory_digest(
        root, source_paths, freshness_extensions={".elisa", ".elisai"}
    )
    recipe_stats, _, _ = stat_inventory_digest(root, recipe_paths)
    source_digest = previous_inputs.get("source_tree_sha256")
    if exact_content or previous_inputs.get("source_tree_stat_fingerprint") != source_stats or not valid_sha256(source_digest):
        source_digest = digest_files(root, source_paths)
    recipe_digest = previous_inputs.get("build_recipe_sha256")
    if exact_content or previous_inputs.get("build_recipe_stat_fingerprint") != recipe_stats or not valid_sha256(recipe_digest):
        recipe_digest = digest_files(root, recipe_paths)
    return {
        "source_tree_sha256": source_digest,
        "source_tree_stat_fingerprint": source_stats,
        "source_tree_max_mtime_ns": source_max_mtime_ns,
        "source_tree_max_mtime_path": source_max_mtime_path,
        "build_recipe_sha256": recipe_digest,
        "build_recipe_stat_fingerprint": recipe_stats,
        "llvm_toolchain": llvm_toolchain_fingerprint(previous_toolchain, exact=exact_toolchain),
        "seed_configuration": seed_configuration_fingerprint(
            previous_inputs.get("seed_configuration"), exact=exact_toolchain
        ),
    }


def snapshot(
    root,
    binary,
    previous_toolchain=None,
    exact_toolchain=False,
    previous_inputs=None,
    exact_content=True,
):
    root = Path(root).resolve()
    binary = Path(binary).resolve()
    previous_inputs = previous_inputs if isinstance(previous_inputs, dict) else {}
    product_identity = file_stat_identity(binary)
    product_digest = previous_inputs.get("product_sha256")
    if (
        exact_content
        or previous_inputs.get("product_stat_identity") != product_identity
        or not valid_sha256(product_digest)
    ):
        product_digest = sha256_file(binary)
        if file_stat_identity(binary) != product_identity:
            raise RuntimeError(f"Stage1 product changed while fingerprinting: {binary}")
    return {
        "schema": SCHEMA,
        "source_revision": source_revision(root),
        **input_fingerprint(
            root,
            previous_toolchain,
            exact_toolchain,
            previous_inputs=previous_inputs,
            exact_content=exact_content,
        ),
        "product_stat_identity": product_identity,
        "product_sha256": product_digest,
    }


def manifest_path(binary):
    return Path(f"{Path(binary)}.provenance.json")


def record(root, binary, expected_inputs=None):
    binary = Path(binary).resolve()
    manifest = manifest_path(binary)
    previous_toolchain = expected_inputs.get("llvm_toolchain") if isinstance(expected_inputs, dict) else None
    data = snapshot(
        root,
        binary,
        previous_toolchain,
        exact_toolchain=True,
        previous_inputs=expected_inputs,
        exact_content=True,
    )
    if expected_inputs is not None:
        if not isinstance(expected_inputs, dict):
            raise RuntimeError("expected Stage1 input fingerprint must be a JSON object")
        changed = [key for key in ("source_tree_sha256", "source_tree_max_mtime_ns",
                                   "source_tree_max_mtime_path", "build_recipe_sha256")
                   if expected_inputs.get(key) != data[key]]
        for key in ("llvm_toolchain", "seed_configuration"):
            if toolchain_content_view(expected_inputs.get(key)) != toolchain_content_view(data.get(key)):
                changed.append(key)
        if changed:
            raise RuntimeError(
                "Stage1 inputs changed during seed; refusing to record provenance for "
                + ", ".join(changed)
            )
    temporary = manifest.with_name(f"{manifest.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, manifest)
    print(f"stage1 provenance: recorded {data['source_revision']} for {binary}")


def check_inputs(root, expected_inputs):
    if not isinstance(expected_inputs, dict):
        raise RuntimeError("expected Stage1 input fingerprint must be a JSON object")
    current = input_fingerprint(
        root,
        expected_inputs.get("llvm_toolchain"),
        exact_toolchain=True,
        previous_inputs=expected_inputs,
    )
    changed = [key for key, value in current.items() if expected_inputs.get(key) != value]
    if changed:
        print(
            "Stage1 inputs changed during seed: " + ", ".join(changed),
            file=sys.stderr,
        )
        return 2
    return 0


def check(root, binary, exact=False):
    binary = Path(binary).resolve()
    manifest = manifest_path(binary)
    try:
        recorded = json.loads(manifest.read_text())
        if not isinstance(recorded, dict) or recorded.get("schema") != SCHEMA:
            recorded_schema = recorded.get("schema") if isinstance(recorded, dict) else None
            print(
                f"stage1 provenance cannot be verified: unsupported schema {recorded_schema!r}; expected {SCHEMA!r}",
                file=sys.stderr,
            )
            return 2
        current = snapshot(
            root,
            binary,
            recorded.get("llvm_toolchain"),
            exact_toolchain=exact,
            previous_inputs=recorded,
            exact_content=exact,
        )
    except (OSError, json.JSONDecodeError, RuntimeError) as error:
        print(f"stage1 provenance cannot be verified: {error}", file=sys.stderr)
        return 2
    # Normal wrapper checks trust a matching local stat tuple as a prior digest attestation.
    # Exact checks rehash every artifact and are required when qualifying benchmarks.
    # The git revision is recorded for humans but not compared: committing after a seed changes
    # HEAD without changing a single input byte.
    cache_metadata = {
        "source_tree_stat_fingerprint",
        "source_tree_max_mtime_ns",
        "source_tree_max_mtime_path",
        "build_recipe_stat_fingerprint",
        "product_stat_identity",
    }
    changed = [key for key, value in current.items()
               if key not in {"source_revision", "llvm_toolchain", "seed_configuration", *cache_metadata}
               and recorded.get(key) != value]
    if toolchain_content_view(current["llvm_toolchain"]) != toolchain_content_view(recorded.get("llvm_toolchain")):
        changed.append("llvm_toolchain")
    if toolchain_content_view(current["seed_configuration"]) != toolchain_content_view(recorded.get("seed_configuration")):
        changed.append("seed_configuration")
    if changed:
        print("stage1 product is stale: provenance mismatch in " + ", ".join(changed), file=sys.stderr)
        return 2
    source_mtime_ns = current["source_tree_max_mtime_ns"]
    product_mtime_ns = current["product_stat_identity"]["mtime_ns"]
    if source_mtime_ns is not None and source_mtime_ns > product_mtime_ns:
        source_path = current["source_tree_max_mtime_path"] or "a compiler source file"
        print(
            f"stage1 product is stale: {source_path} is newer than {binary}",
            file=sys.stderr,
        )
        return 2
    # Silent on success: assert_stage1_fresh.sh runs before EVERY wrapper compile, so a line
    # here lands in the compiler's own output (stdout of `-emit ast`/`fmt`, the first stderr
    # line a parity gate compares). ELISA_PROVENANCE_VERBOSE=1 prints it.
    if os.environ.get("ELISA_PROVENANCE_VERBOSE") == "1":
        print(f"stage1 provenance: current ({current['source_revision']})", file=sys.stderr)
    return 0


def main(argv):
    if len(argv) < 2:
        print("usage: stage1_provenance.py (bootstrap-kind|record|check|check-exact|inputs|check-inputs) ...", file=sys.stderr)
        return 2
    try:
        if argv[1] == "bootstrap-kind":
            if len(argv) != 3:
                raise RuntimeError("usage: stage1_provenance.py bootstrap-kind BOOTSTRAP_COMPILER")
            print(bootstrap_compiler_kind(argv[2]))
            return 0
        if argv[1] == "record":
            if len(argv) not in (4, 5):
                raise RuntimeError("usage: stage1_provenance.py record ROOT BIN [EXPECTED_INPUTS_JSON]")
            expected_inputs = json.loads(argv[4]) if len(argv) == 5 else None
            record(argv[2], argv[3], expected_inputs)
            return 0
        if argv[1] == "check":
            if len(argv) != 4:
                raise RuntimeError("usage: stage1_provenance.py check ROOT BIN")
            return check(argv[2], argv[3])
        if argv[1] == "check-exact":
            if len(argv) != 4:
                raise RuntimeError("usage: stage1_provenance.py check-exact ROOT BIN")
            return check(argv[2], argv[3], exact=True)
        if argv[1] == "inputs":
            if len(argv) not in (3, 4):
                raise RuntimeError("usage: stage1_provenance.py inputs ROOT [PREVIOUS_MANIFEST]")
            previous_inputs = None
            if len(argv) == 4:
                previous_inputs = json.loads(Path(argv[3]).read_text())
                if not isinstance(previous_inputs, dict):
                    raise RuntimeError("previous Stage1 provenance must be a JSON object")
            print(json.dumps(
                input_fingerprint(
                    argv[2],
                    previous_inputs.get("llvm_toolchain") if previous_inputs else None,
                    exact_toolchain=True,
                    previous_inputs=previous_inputs,
                    exact_content=True,
                ),
                separators=(",", ":"),
                sort_keys=True,
            ))
            return 0
        if argv[1] == "check-inputs":
            if len(argv) != 4:
                raise RuntimeError("usage: stage1_provenance.py check-inputs ROOT EXPECTED_INPUTS_JSON")
            return check_inputs(argv[2], json.loads(argv[3]))
        print("usage: stage1_provenance.py (bootstrap-kind|record|check|check-exact|inputs|check-inputs) ...", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as error:
        print(f"stage1 provenance failed: {error}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as error:
        print(f"stage1 provenance failed: invalid input fingerprint: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
