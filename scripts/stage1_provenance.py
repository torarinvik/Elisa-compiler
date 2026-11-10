#!/usr/bin/env python3
"""Record and verify the exact source inputs behind a local Stage1 product."""
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from stage1_artifact_fingerprint import (file_stat_identity, valid_sha256, sha256_file, fingerprint_artifact,
                                         digest_files, stat_inventory_digest)
from stage1_toolchain_fingerprint import (stage1_seed_link_recipe, normalize_linker_probe_argv,
                                          effective_developer_dir, selected_external_linker, llvm_toolchain_fingerprint)


SCHEMA = "elisa-stage1-provenance-v5"
SOURCE_DIRS = ("src", "elisacore_std")
BUILD_RECIPES = (
    "scripts/platform.sh",
    "scripts/elisac_stage1.sh",
    "scripts/stage1_object_cache.py",
    "scripts/stage1_object_cache_files.py",
    "scripts/stage1_object_cache_merger.py",
    "scripts/stage1_shard_cache.py",
    "scripts/stage1_shard_batch.py",
    "scripts/stage1_shard_serialization.py",
    "scripts/elisac_stage1_seed.sh",
    "scripts/stage0_provenance.py",
    "scripts/assert_stage0_fresh.sh",
    "scripts/assert_stage1_fresh.sh",
    "scripts/process_rss.sh",
    "scripts/build_runtime_object.sh",
    "scripts/build_stage1_llvm_bridge.sh",
    "scripts/write_profiler_hook_fallbacks.sh",
    "scripts/stage1_provenance.py",
    "scripts/stage1_artifact_fingerprint.py",
    "scripts/stage1_toolchain_fingerprint.py",
)


def bootstrap_compiler_kind(path):
    """Identify the bootstrap implementation from artifact provenance, not its filename."""
    path = Path(path).expanduser().resolve()
    # ELISACORE_BIN may be the oracle memo (tools/s0cache), which only wraps the real stage0
    # binary named by ELISA_S0_REAL (the same mapping assert_stage0_fresh.sh applies).
    if path.name == "s0cache" and os.environ.get("ELISA_S0_REAL"):
        path = Path(os.environ["ELISA_S0_REAL"]).expanduser().resolve()
    explicit = os.environ.get("ELISA_STAGE1_SEED_BOOTSTRAP_KIND")
    if explicit:
        if explicit not in ("stage0", "stage1"):
            raise RuntimeError(
                "ELISA_STAGE1_SEED_BOOTSTRAP_KIND must be stage0 or stage1 "
                f"(got {explicit!r})"
            )
        return explicit
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
    # Stage0 is the Go compiler. Go build metadata identifies it even after a copy or rename,
    # while a filename alone cannot distinguish a renamed Stage1 from an arbitrary executable.
    try:
        go_build = subprocess.run(
            ["go", "version", "-m", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        go_build = None
    if go_build is not None and go_build.returncode == 0:
        for line in go_build.stdout.splitlines():
            fields = line.split()
            if fields[:2] == ["path", "elisacore/src"] or fields[:2] == ["mod", "elisacore"]:
                return "stage0"
    raise RuntimeError(
        f"cannot determine bootstrap compiler stage for {path}; use a Stage1 provenance "
        "manifest or set ELISA_STAGE1_SEED_BOOTSTRAP_KIND explicitly"
    )


def toolchain_content_view(value):
    if isinstance(value, dict):
        stat_fields = {"size", "mtime_ns", "ctime_ns", "device", "inode"}
        return {
            key: toolchain_content_view(item)
            for key, item in value.items()
            if key not in stat_fields and key != "linker_probe_cache_key"
        }
    if isinstance(value, list):
        return [toolchain_content_view(item) for item in value]
    return value


def selected_seed_bootstrap():
    """Resolve the optional oracle cache the same way as Stage0 freshness checks."""
    explicit = (os.environ.get("ELISA_STAGE1_SEED_BOOTSTRAP_BIN")
                or os.environ.get("ELISA_STAGE1_SEED_STAGE0_BIN")
                or os.environ.get("BOOTSTRAP_BIN") or os.environ.get("STAGE0_BIN"))
    if explicit:
        return explicit
    oracle = os.environ.get("ELISACORE_BIN")
    if oracle and Path(oracle).name == "s0cache":
        return os.environ.get("ELISA_S0_REAL") or oracle
    return oracle


def seed_configuration_fingerprint(previous=None, exact=False):
    previous = previous if isinstance(previous, dict) else {}
    previous_bootstrap = previous.get("bootstrap_compiler")
    previous_runtime = previous.get("bootstrap_runtime_object")
    bootstrap_path = selected_seed_bootstrap()
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
        host_os, seed_link_flags, profiler_hook_mode = stage1_seed_link_recipe()
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
    source_stats, source_writes, source_max_mtime_ns, source_max_mtime_path = stat_inventory_digest(
        root, source_paths, freshness_extensions={".elisa", ".elisai"}
    )
    recipe_stats, recipe_writes, _, _ = stat_inventory_digest(root, recipe_paths)
    source_digest = previous_inputs.get("source_tree_sha256")
    if exact_content or previous_inputs.get("source_tree_stat_fingerprint") != source_stats or not valid_sha256(source_digest):
        source_digest = digest_files(root, source_paths)
    recipe_digest = previous_inputs.get("build_recipe_sha256")
    if exact_content or previous_inputs.get("build_recipe_stat_fingerprint") != recipe_stats or not valid_sha256(recipe_digest):
        recipe_digest = digest_files(root, recipe_paths)
    return {
        "source_tree_sha256": source_digest,
        "source_tree_stat_fingerprint": source_stats,
        "source_tree_write_fingerprint": source_writes,
        "source_tree_max_mtime_ns": source_max_mtime_ns,
        "source_tree_max_mtime_path": source_max_mtime_path,
        "build_recipe_sha256": recipe_digest,
        "build_recipe_stat_fingerprint": recipe_stats,
        "build_recipe_write_fingerprint": recipe_writes,
        "llvm_toolchain": llvm_toolchain_fingerprint(previous_toolchain, exact=exact_toolchain),
        "seed_configuration": seed_configuration_fingerprint(
            previous_inputs.get("seed_configuration"), exact=exact_toolchain
        ),
    }


def input_fingerprint_keys():
    return (
        "source_tree_sha256", "source_tree_stat_fingerprint", "source_tree_write_fingerprint",
        "source_tree_max_mtime_ns", "source_tree_max_mtime_path", "build_recipe_sha256",
        "build_recipe_stat_fingerprint", "build_recipe_write_fingerprint", "llvm_toolchain",
        "seed_configuration",
    )


def snapshot(
    root,
    binary,
    previous_toolchain=None,
    exact_toolchain=False,
    previous_inputs=None,
    exact_content=True,
    verified_inputs=None,
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
    data = {
        "schema": SCHEMA,
        "source_revision": source_revision(root),
        **(verified_inputs if verified_inputs is not None else input_fingerprint(
            root,
            previous_toolchain,
            exact_toolchain,
            previous_inputs=previous_inputs,
            exact_content=exact_content,
        )),
        "product_stat_identity": product_identity,
        "product_sha256": product_digest,
    }
    linker = os.environ.get("ELISA_STAGE1_SEED_LINKER")
    if linker:
        # LLD selects its driver from argv[0]; resolving ld64.lld to lld before
        # invoking it loses the Darwin driver selection.
        executable = Path(linker).absolute()
        resolved = executable.resolve(strict=True)
        version = subprocess.run([str(executable), "--version"], check=True,
                                 capture_output=True, text=True)
        data["seed_linker"] = {
            "path": str(executable),
            "resolved_path": str(resolved),
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            "version": version.stdout.strip(),
        }
    return data
    linker = os.environ.get("ELISA_STAGE1_SEED_LINKER")
    if linker:
        # LLD selects its driver from argv[0]; resolving ld64.lld to lld before
        # invoking it loses the Darwin driver selection.
        executable = Path(linker).absolute()
        resolved = executable.resolve(strict=True)
        version = subprocess.run([str(executable), "--version"], check=True,
                                 capture_output=True, text=True)
        data["seed_linker"] = {
            "path": str(executable),
            "resolved_path": str(resolved),
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            "version": version.stdout.strip(),
        }
    return data


def manifest_path(binary):
    return Path(f"{Path(binary)}.provenance.json")


def record_verified(root, binary, inputs):
    """Record a seed product against the exact input fingerprint its build used.

    The seed computed `inputs` (content and toolchain, exactly) while the build ran
    and check-inputs proved no write happened from before the build until after
    it, so they describe the product exactly; only the product itself is hashed
    here. A later edit still makes `check` report the product stale.
    """
    if not isinstance(inputs, dict) or set(inputs) != set(input_fingerprint_keys()):
        raise RuntimeError("verified Stage1 input fingerprint is incomplete")
    binary = Path(binary).resolve()
    manifest = manifest_path(binary)
    data = snapshot(root, binary, exact_content=True, verified_inputs=inputs)
    temporary = manifest.with_name(f"{manifest.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, manifest)
    print(f"stage1 provenance: recorded {data['source_revision']} for {binary}")


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


WRITE_FINGERPRINT_KEYS = ("source_tree_write_fingerprint", "build_recipe_write_fingerprint")


def write_fingerprint(root):
    """Stat-only (no content, no toolchain) snapshot of every source and recipe write."""
    root = Path(root).resolve()
    _, source_writes, _, _ = stat_inventory_digest(root, [root / name for name in SOURCE_DIRS])
    _, recipe_writes, _, _ = stat_inventory_digest(root, [root / name for name in BUILD_RECIPES])
    return dict(zip(WRITE_FINGERPRINT_KEYS, (source_writes, recipe_writes)))


def check_inputs(root, expected_inputs, before_build=None):
    if not isinstance(expected_inputs, dict):
        raise RuntimeError("expected Stage1 input fingerprint must be a JSON object")
    # A full fingerprint may be computed while the build runs. Then the stat-only
    # snapshot taken before the build is the anchor: the full fingerprint and the
    # current tree must both match it, so no write happened from before the build
    # started until now and the hashed content is what the build read.
    if before_build is not None:
        if not isinstance(before_build, dict) or any(
            expected_inputs.get(key) != before_build.get(key) for key in WRITE_FINGERPRINT_KEYS
        ):
            print("Stage1 inputs changed during seed: write fingerprint before build", file=sys.stderr)
            return 2
    current = input_fingerprint(
        root,
        expected_inputs.get("llvm_toolchain"),
        exact_toolchain=True,
        previous_inputs=expected_inputs,
    )
    # The write fingerprints and content digests decide whether inputs changed during
    # the build; the ctime-bearing stat fingerprints only gate digest reuse.
    reuse_only = {"source_tree_stat_fingerprint", "build_recipe_stat_fingerprint"}
    changed = [
        key
        for key, value in current.items()
        if key not in reuse_only and (
            toolchain_content_view(expected_inputs.get(key))
            != toolchain_content_view(value)
            if key in {"llvm_toolchain", "seed_configuration"}
            else expected_inputs.get(key) != value
        )
    ]
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
        "source_tree_write_fingerprint",
        "source_tree_max_mtime_ns",
        "source_tree_max_mtime_path",
        "build_recipe_stat_fingerprint",
        "build_recipe_write_fingerprint",
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
    for name in ("LIBRARY_PATH", "SDKROOT"):
        present = os.environ.pop(f"ELISA_PROVENANCE_{name}_SET", None)
        value = os.environ.pop(f"ELISA_PROVENANCE_{name}_VALUE", "")
        if present == "x":
            os.environ[name] = value
        elif present == "":
            os.environ.pop(name, None)

    if len(argv) < 2:
        print("usage: stage1_provenance.py (bootstrap-kind|record|check|check-exact|inputs|write-fingerprint|check-inputs) ...", file=sys.stderr)
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
        if argv[1] == "record-verified":
            if len(argv) != 5:
                raise RuntimeError("usage: stage1_provenance.py record-verified ROOT BIN VERIFIED_INPUTS_JSON")
            record_verified(argv[2], argv[3], json.loads(argv[4]))
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
        if argv[1] == "write-fingerprint":
            if len(argv) != 3:
                raise RuntimeError("usage: stage1_provenance.py write-fingerprint ROOT")
            print(json.dumps(write_fingerprint(argv[2]), separators=(",", ":"), sort_keys=True))
            return 0
        if argv[1] == "check-inputs":
            if len(argv) not in (4, 5):
                raise RuntimeError("usage: stage1_provenance.py check-inputs ROOT EXPECTED_INPUTS_JSON [WRITE_FINGERPRINT_BEFORE_BUILD_JSON]")
            return check_inputs(argv[2], json.loads(argv[3]), json.loads(argv[4]) if len(argv) == 5 else None)
        print("usage: stage1_provenance.py (bootstrap-kind|record|check|check-exact|inputs|write-fingerprint|check-inputs) ...", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as error:
        print(f"stage1 provenance failed: {error}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as error:
        print(f"stage1 provenance failed: invalid input fingerprint: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
