"""Fingerprint Stage1 linker and LLVM toolchain selection."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from stage1_artifact_fingerprint import fingerprint_artifact


def stage1_seed_link_recipe():
    host_os = os.uname().sysname
    if host_os == "Linux":
        return host_os, ["-no-pie", "-Wl,--gc-sections"], "--host-callbacks"
    if host_os == "Darwin":
        # Make the directory precedence used for -l resolution explicit. The
        # provenance resolver uses the same left-to-right rule below.
        return host_os, ["-Wl,-dead_strip", "-Wl,-stack_size,0x20000000", "-Wl,-search_paths_first"], ""
    raise RuntimeError(f"unsupported Stage1 seed host OS: {host_os}")

def normalize_linker_probe_argv(argv):
    # Clang's `-###` prints a randomized temporary object name for the `/dev/null`
    # translation unit. That path is not part of the selected linker or its recipe,
    # and would make exact Stage1 input fingerprints differ on every invocation.
    temporary_directory = Path(tempfile.gettempdir()).resolve()
    normalized = []
    search_directories = set()
    for argument in argv:
        # Clang emits joined -L options, including inherited LIBRARY_PATH entries.
        # Repeating exactly the same directory cannot alter its first-match search
        # order. Preserve the first occurrence; do not normalize library options,
        # distinct spellings, or the relative order of different directories.
        if argument.startswith("-L") and len(argument) > 2:
            if argument in search_directories:
                continue
            search_directories.add(argument)
        path = Path(argument)
        if (
            re.fullmatch(r"null-[A-Za-z0-9]+\.o", path.name)
            and path.parent.resolve() == temporary_directory
        ):
            normalized.append("<clang-stage1-probe-object>")
        else:
            normalized.append(argument)
    return normalized

def effective_developer_dir(host_os):
    raw = os.environ.get("DEVELOPER_DIR", "")
    if not raw and host_os == "Darwin" and Path("/Library/Developer/CommandLineTools").is_dir():
        raw = "/Library/Developer/CommandLineTools"
    return str(Path(raw).expanduser().resolve()) if raw else None

def selected_external_linker(clang, clang_artifact, config_libdir, link_flags, previous=None, exact=False):
    previous = previous if isinstance(previous, dict) else {}
    host_os, seed_link_flags, _ = stage1_seed_link_recipe()
    developer_dir = effective_developer_dir(host_os)
    executable_link_flags = os.environ.get("ELISA_LINK_EXE_FLAGS", "")
    path_env = os.environ.get("PATH", "")
    probe_env = os.environ.copy()
    if developer_dir:
        probe_env["DEVELOPER_DIR"] = developer_dir
    else:
        probe_env.pop("DEVELOPER_DIR", None)
    # Hash the exact inherited probe environment, without persisting its values.
    probe_env_digest = hashlib.sha256(
        json.dumps(probe_env, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    probe_environment = {
        "environment_sha256": probe_env_digest,
        "host_os": host_os,
        "developer_dir": developer_dir,
        "path": path_env,
        "sdk_root": os.environ.get("SDKROOT", ""),
        "deployment_target": os.environ.get("MACOSX_DEPLOYMENT_TARGET", ""),
        "clang_path": str(clang),
        "clang_artifact_sha256": clang_artifact["sha256"],
        "config_libdir": str(config_libdir),
        "seed_link_flags": seed_link_flags,
        "llvm_link_flags": link_flags,
        "executable_link_flags": executable_link_flags,
    }
    probe_cache_key = hashlib.sha256(
        json.dumps(probe_environment, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cached = previous.get("external_linker")
    if (
        not exact
        and isinstance(cached, dict)
        and cached.get("linker_probe_cache_key") == probe_cache_key
        and cached.get("clang_artifact_sha256") == clang_artifact["sha256"]
        and isinstance(cached.get("path"), str)
        and isinstance(cached.get("command"), str)
        and isinstance(cached.get("link_command"), list)
        and isinstance(cached.get("artifact"), dict)
    ):
        linker_command = cached.get("command")
        linker_argv = cached.get("link_command")
        linker_path = Path(cached["path"]).resolve()
    else:
        probe_args = [
            str(clang), "-###", "-fno-builtin", *seed_link_flags,
            "-o", os.devnull, "-x", "c", os.devnull,
            f"-L{config_libdir}", *shlex.split(link_flags),
            *shlex.split(executable_link_flags), f"-Wl,-rpath,{config_libdir}",
        ]
        try:
            result = subprocess.run(
                probe_args, capture_output=True, text=True, env=probe_env, check=True
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"could not resolve the Stage1 external linker with {clang}: {error}") from error
        linker_argv = None
        linker_command = None
        linker_names = {"ld", "ld64", "ld64.lld", "ld.lld", "ld.gold", "ld.bfd", "ld.mold"}
        for line in result.stderr.splitlines():
            try:
                argv = shlex.split(line)
            except ValueError:
                continue
            if not argv or Path(argv[0]).name not in linker_names:
                continue
            linker_command = argv[0]
            # Clang's random temporary object path is normalized after linker
            # selection so the fingerprint stays stable across probe runs.
            linker_argv = argv
            break
        if linker_command is None:
            diagnostic = (result.stderr or result.stdout).strip().splitlines()
            excerpt = diagnostic[-1] if diagnostic else "no linker command in Clang -### output"
            raise RuntimeError(f"could not identify the Stage1 external linker: {excerpt}")
        resolved_command = shutil.which(linker_command, path=path_env) or linker_command
        linker_path = Path(resolved_command).expanduser().resolve()
    linker_argv = normalize_linker_probe_argv(linker_argv) if linker_argv else None
    if not linker_path.is_file() or not os.access(linker_path, os.X_OK):
        raise RuntimeError(f"selected Stage1 external linker is not executable: {linker_path}")
    linker_artifact = fingerprint_artifact(
        linker_path,
        cached.get("artifact") if isinstance(cached, dict) and cached.get("path") == str(linker_path) else None,
        exact=exact,
        description="Stage1 external linker",
    )
    version = ""
    for argument in ("-v", "--version"):
        try:
            version_result = subprocess.run(
                [str(linker_path), argument], capture_output=True, text=True
            )
        except OSError:
            continue
        lines = (version_result.stdout + "\n" + version_result.stderr).splitlines()
        version = next((line.strip() for line in lines if line.strip()), "")
        if version:
            break
    return {
        "command": linker_command,
        "path": str(linker_path),
        "artifact": linker_artifact,
        "version": version,
        "developer_dir": developer_dir,
        "link_command": linker_argv,
        "clang_artifact_sha256": clang_artifact["sha256"],
        "linker_probe_cache_key": probe_cache_key,
    }

def llvm_toolchain_fingerprint(previous=None, exact=False):
    previous = previous if isinstance(previous, dict) else {}
    raw_config = os.environ.get("LLVM_CONFIG") or previous.get("llvm_config_path")
    if not raw_config:
        raise RuntimeError("LLVM_CONFIG is required to fingerprint Stage1; source scripts/platform.sh first")
    previous_artifacts = {}
    for key in ("llvm_config_artifact", "clang_artifact", "llvm_cxx_artifact"):
        artifact = previous.get(key)
        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
            previous_artifacts[artifact["path"]] = artifact
    for key in ("dynamic_libraries", "static_archives", "link_libraries"):
        artifacts = previous.get(key)
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                    previous_artifacts[artifact["path"]] = artifact
    previous_linker = previous.get("external_linker")
    if isinstance(previous_linker, dict):
        artifact = previous_linker.get("artifact")
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
    raw_config_libdir = previous.get("llvm_config_libdir") if config_unchanged and not exact else None
    config_libdir = resolved_directory(
        raw_config_libdir or llvm_config("--libdir"), "llvm-config library directory"
    )
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
    raw_cxx = os.environ.get("ELISA_LLVM_CXX") or str(Path(llvm_config("--bindir")) / "clang++")
    cxx = Path(shutil.which(raw_cxx) or raw_cxx).resolve()
    if not cxx.is_file() or not os.access(cxx, os.X_OK):
        raise RuntimeError(f"selected LLVM C++ compiler is not executable: {cxx}")
    llvm_cxx_artifact = artifact_record(cxx)
    llvm_cxxflags = llvm_config("--cxxflags")
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
    external_linker = selected_external_linker(
        clang,
        clang_artifact,
        config_libdir,
        link_flags,
        previous,
        exact=exact,
    )
    link_tokens = shlex.split(link_flags)
    executable_link_tokens = shlex.split(os.environ.get("ELISA_LINK_EXE_FLAGS", ""))
    all_link_tokens = [*link_tokens, *executable_link_tokens]
    link_search_dirs = [Path(config_libdir)]
    llvm_library_names = []
    direct_link_libraries = []
    def add_search_directory(raw_path):
        path = Path(raw_path).expanduser()
        link_search_dirs.append(path if path.is_absolute() else (Path.cwd() / path).resolve())

    def add_search_paths(tokens):
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token == "-L" and index + 1 < len(tokens):
                add_search_directory(tokens[index + 1])
                index += 2
                continue
            if token.startswith("-L") and len(token) > 2:
                add_search_directory(token[2:])
            elif token.startswith("-Wl,"):
                forwarded = token[4:].split(",")
                for part_index, part in enumerate(forwarded):
                    if part == "-L" and part_index + 1 < len(forwarded):
                        add_search_directory(forwarded[part_index + 1])
                    elif part.startswith("-L") and len(part) > 2:
                        add_search_directory(part[2:])
            index += 1

    add_search_paths(all_link_tokens)
    index = 0
    while index < len(all_link_tokens):
        token = all_link_tokens[index]
        if token == "-l" and index + 1 < len(all_link_tokens):
            library_name = all_link_tokens[index + 1]
            index += 2
        elif token.startswith("-l") and len(token) > 2:
            library_name = token[2:]
            index += 1
        else:
            library_name = None
            index += 1
        if library_name and (library_name.startswith("LLVM") or library_name.startswith(":libLLVM")):
            llvm_library_names.append(library_name)
        elif token.endswith((".dylib", ".tbd", ".so", ".a", ".lib")) or ".so." in token:
            candidate = Path(token).expanduser()
            if candidate.is_file():
                direct_link_libraries.append(candidate.resolve())

    static_link = any(
        "start-group" in token or "-Bstatic" in token or token in ("-static",)
        or token.endswith((".a", ".lib"))
        for token in all_link_tokens
    )
    dynamic_link = bool(llvm_library_names) or any(
        Path(path).name.startswith("libLLVM")
        and (str(path).endswith((".dylib", ".tbd", ".so")) or ".so." in str(path))
        for path in direct_link_libraries
    )
    link_mode = "static" if static_link else ("dynamic" if dynamic_link else "unknown")
    if link_mode == "unknown":
        raise RuntimeError("ELISA_LLVM_LIBS does not identify whether Stage1 links LLVM statically or dynamically")

    def resolve_library_name(library_name):
        if library_name.startswith(":"):
            candidate_names = [library_name[1:]]
        else:
            if static_link:
                suffixes = (".a", ".lib")
            elif sys.platform == "darwin":
                suffixes = (".dylib", ".tbd", ".a")
            else:
                suffixes = (".so", ".a")
            candidate_names = [f"lib{library_name}{suffix}" for suffix in suffixes]
        # The Stage1 seed passes llvm-config --libdir before ELISA_LLVM_LIBS.
        # On Darwin, -search_paths_first makes this per-directory suffix order
        # the same one the selected linker uses.
        for directory in link_search_dirs:
            for candidate_name in candidate_names:
                candidate = directory / candidate_name
                if candidate.is_file():
                    return candidate.resolve()
        raise RuntimeError(
            f"could not resolve linked LLVM library -l{library_name} using Stage1 link search order"
        )

    link_library_paths = set(direct_link_libraries)
    for library_name in llvm_library_names:
        link_library_paths.add(resolve_library_name(library_name))
    link_libraries = [artifact_record(path) for path in sorted(link_library_paths)]
    static_archives = [
        artifact for artifact in link_libraries if artifact["path"].endswith((".a", ".lib"))
    ]
    dynamic_libraries = [
        artifact for artifact in link_libraries
        if artifact["path"].endswith((".dylib", ".tbd", ".so")) or ".so." in artifact["path"]
    ]

    return {
        "llvm_config_path": str(config),
        "llvm_config_artifact": config_artifact,
        "llvm_version": version,
        "llvm_bindir": bindir,
        "llvm_libdir": libdir,
        "llvm_config_libdir": config_libdir,
        "clang_path": str(clang),
        "clang_artifact": clang_artifact,
        "llvm_cxx_artifact": llvm_cxx_artifact,
        "llvm_cxxflags": llvm_cxxflags,
        "clang_version": clang_version,
        "external_linker": external_linker,
        "link_mode": link_mode,
        "link_flags": link_flags,
        "dynamic_libraries": dynamic_libraries,
        "static_archives": static_archives,
        "link_libraries": link_libraries,
    }
