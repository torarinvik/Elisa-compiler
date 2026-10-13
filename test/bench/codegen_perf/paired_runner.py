#!/usr/bin/env python3
"""Orchestrate exact-parity A/B runs while holding one host lock throughout."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
RUNNER = SCRIPT_DIR / "cross_language.sh"
REPORTER = SCRIPT_DIR / "paired_report.py"
PROVENANCE_INPUTS = (
    "src",
    "elisacore_std",
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
VERIFIED_FILE_HASHES: dict[str, str] = {}
VERIFIED_TIMING_SAMPLE_BYTES: dict[str, bytes] = {}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root: Path) -> dict[str, object]:
    paths: list[Path] = []
    for relative in PROVENANCE_INPUTS:
        input_path = root / relative
        if input_path.is_dir():
            paths.extend(candidate for candidate in input_path.rglob("*") if candidate.is_file())
        elif input_path.is_file():
            paths.append(input_path)
        else:
            raise RuntimeError(f"compiler provenance input is missing under {root}: {relative}")
    rows = [
        {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}
        for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix())
    ]
    manifest_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(manifest_bytes).hexdigest(), "files": rows}


def run_suite(
    compiler: Path,
    source_root: Path,
    output: Path,
    lock_fd: int,
    *,
    preflight_only: bool = False,
    reference_fingerprint: Path | None = None,
) -> None:
    environment = os.environ.copy()
    environment["ELISA_STAGE1_BIN"] = str(compiler)
    environment["ELISA_STAGE1_PROVENANCE_ROOT"] = str(source_root)
    environment["ELISA_BENCH_LOCK_FD"] = str(lock_fd)
    if preflight_only:
        environment["ELISA_BENCH_PREFLIGHT_ONLY"] = "1"
    else:
        environment.pop("ELISA_BENCH_PREFLIGHT_ONLY", None)
    if reference_fingerprint is not None:
        environment["ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT"] = str(reference_fingerprint)
    else:
        environment.pop("ELISA_BENCH_EXPECT_CANONICAL_FINGERPRINT", None)
    subprocess.run(
        [str(RUNNER), str(output)],
        check=True,
        env=environment,
        pass_fds=(lock_fd,),
    )


def preflight_record(directory: Path, compiler: Path, source_root: Path) -> dict[str, object]:
    if not (directory / "PREFLIGHT_COMPLETE").is_file() or (directory / "ABORTED.txt").exists():
        raise RuntimeError(f"{directory} did not complete its exact correctness preflight")
    values: dict[str, str] = {}
    for line in (directory / "metadata.txt").read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    if values.get("elisa_product_sha256") != digest(compiler):
        raise RuntimeError(f"{directory} metadata does not identify {compiler}")
    if values.get("elisa_provenance_source_root") != str(source_root):
        raise RuntimeError(f"{directory} metadata does not identify source root {source_root}")
    fingerprint_path = directory / "canonical_workload_fingerprint.json"
    try:
        record = json.loads(fingerprint_path.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{directory} has an unreadable canonical workload fingerprint") from error
    if not isinstance(record, dict):
        raise RuntimeError(f"{directory} canonical workload fingerprint must be a JSON object")
    if record.get("schema") != "canonical-codegen-workloads-v5":
        raise RuntimeError(f"{directory} has an unsupported canonical workload fingerprint schema")

    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("schema") != record["schema"]:
        raise RuntimeError(f"{directory} has a malformed canonical workload payload")
    scope = payload.get("scope")
    if not isinstance(scope, str) or scope not in {"compile_only", "full_runtime"}:
        raise RuntimeError(f"{directory} has an unsupported canonical workload scope")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if record.get("fingerprint_sha256") != hashlib.sha256(canonical).hexdigest():
        raise RuntimeError(f"{directory} has an invalid canonical workload fingerprint hash")

    provenance = record.get("run_provenance")
    if not isinstance(provenance, dict):
        raise RuntimeError(f"{directory} has no run provenance")
    if provenance.get("scope") != scope:
        raise RuntimeError(f"{directory} has inconsistent run provenance scope")
    binding = json.dumps(
        {"payload": payload, "run_provenance": provenance},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if record.get("run_fingerprint_sha256") != hashlib.sha256(binding).hexdigest():
        raise RuntimeError(f"{directory} has an invalid run fingerprint")
    runtime_hash = record.get("runtime_artifact_sha256")
    if (
        not isinstance(runtime_hash, str)
        or runtime_hash != provenance.get("runtime_artifact_sha256")
    ):
        raise RuntimeError(f"{directory} has inconsistent runtime artifact provenance")
    return record


def read_metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def verify_file_hash(path: Path, expected_hash: object, label: str) -> None:
    path = path.resolve()
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError(f"{label} has an invalid SHA-256")
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    actual_hash = VERIFIED_FILE_HASHES.get(str(path))
    if actual_hash is None:
        actual_hash = digest(path)
        VERIFIED_FILE_HASHES[str(path)] = actual_hash
    if actual_hash != expected_hash:
        raise ValueError(f"{label} changed: {path}")


def verified_timing_sample_bytes(path: Path) -> bytes:
    resolved = str(path.resolve())
    content = VERIFIED_TIMING_SAMPLE_BYTES.get(resolved)
    if content is None:
        raise ValueError(f"timing sample bytes were not verified: {resolved}")
    return content


def verify_run_artifacts(
    directory: Path,
    fingerprint: dict[str, object],
    run_metadata: dict[str, str],
) -> None:
    provenance = fingerprint.get("run_provenance")
    if not isinstance(provenance, dict):
        raise ValueError(f"{directory} has no run provenance")

    source_manifest_path = directory / "sources.sha256"
    verify_file_hash(
        source_manifest_path,
        provenance.get("source_manifest_sha256"),
        f"{directory.name} source manifest",
    )
    for line in source_manifest_path.read_text().splitlines():
        expected, separator, relative = line.partition("  ")
        if not separator:
            raise ValueError(f"{directory.name} has a malformed source manifest")
        verify_file_hash(ROOT / relative, expected, f"{directory.name} source input")

    toolchain_path = directory / "toolchain.before.sha256"
    verify_file_hash(
        toolchain_path,
        provenance.get("toolchain_manifest_sha256"),
        f"{directory.name} toolchain manifest",
    )
    parsed_toolchain = []
    for line in toolchain_path.read_text().splitlines():
        expected, separator, raw_path = line.partition("  ")
        if not separator or not raw_path:
            raise ValueError(f"{directory.name} has a malformed toolchain manifest")
        path = Path(raw_path).resolve()
        verify_file_hash(path, expected, f"{directory.name} toolchain input")
        parsed_toolchain.append({"path": str(path), "sha256": expected.lower()})
    parsed_toolchain.sort(key=lambda row: (row["path"], row["sha256"]))
    if parsed_toolchain != provenance.get("toolchain_manifest"):
        raise ValueError(f"{directory.name} toolchain manifest differs from run provenance")

    verify_file_hash(
        directory / "metadata.txt",
        provenance.get("metadata_sha256"),
        f"{directory.name} metadata",
    )
    verify_file_hash(
        directory / "host_qualification.json",
        provenance.get("host_qualification_sha256"),
        f"{directory.name} host qualification",
    )
    runtime_path = run_metadata.get("elisa_runtime_object")
    if not runtime_path:
        raise ValueError(f"{directory.name} metadata has no runtime object path")
    verify_file_hash(
        Path(runtime_path),
        provenance.get("runtime_artifact_sha256"),
        f"{directory.name} runtime artifact",
    )

    timing_manifest_path = directory / "timing_samples.sha256"
    timing_manifest_hash = provenance.get("timing_samples_manifest_sha256")
    if timing_manifest_hash is None:
        if not (directory / "PREFLIGHT_COMPLETE").is_file() or timing_manifest_path.exists():
            raise ValueError(f"{directory.name} has no timing sample manifest")
    else:
        if not isinstance(timing_manifest_hash, str) or len(timing_manifest_hash) != 64:
            raise ValueError(f"{directory.name} timing sample manifest has an invalid SHA-256")
        timing_manifest_bytes = timing_manifest_path.read_bytes()
        if hashlib.sha256(timing_manifest_bytes).hexdigest() != timing_manifest_hash:
            raise ValueError(f"{directory.name} timing sample manifest changed: {timing_manifest_path}")
        expected_timing_names = {"build_samples.csv", "compile_samples.csv"}
        if provenance.get("scope") == "full_runtime":
            expected_timing_names.add("samples.csv")
        elif provenance.get("scope") != "compile_only":
            raise ValueError(f"{directory.name} has an invalid timing sample scope")
        if "retired_instruction_counter" in provenance:
            expected_timing_names.add("counter_samples.csv")
        timing_rows: dict[str, str] = {}
        try:
            timing_manifest_text = timing_manifest_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"{directory.name} timing sample manifest is not valid UTF-8") from error
        for line in timing_manifest_text.splitlines():
            expected, separator, relative = line.partition("  ")
            if not separator or relative in timing_rows:
                raise ValueError(f"{directory.name} has a malformed timing sample manifest")
            if Path(relative).name != relative or relative not in expected_timing_names:
                raise ValueError(f"{directory.name} has an unexpected timing sample path: {relative}")
            timing_rows[relative] = expected
        if set(timing_rows) != expected_timing_names:
            raise ValueError(f"{directory.name} timing sample manifest has incomplete coverage")
        for relative, expected in timing_rows.items():
            sample_path = (directory / relative).resolve()
            sample_bytes = sample_path.read_bytes()
            if hashlib.sha256(sample_bytes).hexdigest() != expected:
                raise ValueError(f"{directory.name} timing sample changed: {sample_path}")
            VERIFIED_TIMING_SAMPLE_BYTES[str(sample_path)] = sample_bytes

    shared_runtime = provenance.get("shared_runtime_source_manifest")
    if not isinstance(shared_runtime, dict) or not isinstance(shared_runtime.get("files"), list):
        raise ValueError(f"{directory.name} has no shared runtime source manifest")
    runtime_rows = shared_runtime["files"]
    runtime_manifest_bytes = json.dumps(runtime_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if shared_runtime.get("sha256") != hashlib.sha256(runtime_manifest_bytes).hexdigest():
        raise ValueError(f"{directory.name} shared runtime source manifest hash is invalid")
    for row in runtime_rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError(f"{directory.name} has a malformed shared runtime source row")
        verify_file_hash(ROOT / row["path"], row.get("sha256"), f"{directory.name} shared runtime source")


def stable_toolchain_identity(
    fingerprint: dict[str, object],
    pair_metadata: dict[str, object],
    run_metadata: dict[str, str],
) -> list[dict[str, str]]:
    provenance = fingerprint.get("run_provenance")
    rows = provenance.get("toolchain_manifest") if isinstance(provenance, dict) else None
    if not isinstance(rows, list):
        raise ValueError("run provenance has no toolchain manifest")
    compiler_paths = {
        str(Path(str(pair_metadata[key])).resolve())
        for key in ("reference_binary", "candidate_binary")
        if key in pair_metadata
    }
    if len(compiler_paths) != 2:
        raise ValueError("paired metadata is missing a reference or candidate compiler path")
    runtime_path = run_metadata.get("elisa_runtime_object")
    if not runtime_path:
        raise ValueError("preflight metadata has no runtime object path")
    compiler_paths.add(str(Path(runtime_path).resolve()))
    stable = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
            raise ValueError("run provenance has a malformed toolchain manifest")
        path = str(Path(row["path"]).resolve())
        if path in compiler_paths or path.endswith(".provenance.json"):
            continue
        stable.append({"path": path, "sha256": row["sha256"]})
    return sorted(stable, key=lambda row: (row["path"], row["sha256"]))


def paired_input_identity(
    fingerprint: dict[str, object],
    pair_metadata: dict[str, object],
    run_metadata: dict[str, str],
) -> dict[str, object]:
    payload = fingerprint.get("payload")
    provenance = fingerprint.get("run_provenance")
    if not isinstance(payload, dict) or not isinstance(provenance, dict):
        raise ValueError("preflight fingerprint has no payload or run provenance")
    source_hash = provenance.get("source_manifest_sha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash.lower()):
        raise ValueError("preflight has no valid source manifest hash")
    comparator = payload.get("comparator_toolchain")
    if not isinstance(comparator, list) or not comparator:
        raise ValueError("preflight has no comparator toolchain identity")
    shared_runtime = provenance.get("shared_runtime_source_manifest")
    if not isinstance(shared_runtime, dict) or not isinstance(shared_runtime.get("files"), list):
        raise ValueError("preflight has no shared runtime source manifest")
    runtime_rows = shared_runtime["files"]
    runtime_manifest = json.dumps(runtime_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if shared_runtime.get("sha256") != hashlib.sha256(runtime_manifest).hexdigest():
        raise ValueError("preflight shared runtime source manifest hash is invalid")
    runtime_hash = provenance.get("runtime_artifact_sha256")
    if not isinstance(runtime_hash, str) or len(runtime_hash) != 64 or any(c not in "0123456789abcdef" for c in runtime_hash.lower()):
        raise ValueError("preflight has no valid runtime artifact hash")
    return {
        "source_manifest_sha256": source_hash,
        "stable_toolchain_manifest": stable_toolchain_identity(fingerprint, pair_metadata, run_metadata),
        "comparator_toolchain": comparator,
        "shared_runtime_source_manifest": shared_runtime,
        "retired_instruction_counter": provenance.get(
            "retired_instruction_counter", run_metadata.get("retired_instruction_counter")
        ),
    }


def main(arguments: list[str]) -> int:
    if len(arguments) not in (4, 5):
        raise SystemExit(
            "usage: paired_cross_language.sh REFERENCE_STAGE1 REFERENCE_SOURCE_ROOT "
            "CANDIDATE_STAGE1 CANDIDATE_SOURCE_ROOT [OUTPUT_DIR]"
        )
    reference_bin = Path(arguments[0]).expanduser().resolve(strict=True)
    reference_root = Path(arguments[1]).expanduser().resolve(strict=True)
    candidate_bin = Path(arguments[2]).expanduser().resolve(strict=True)
    candidate_root = Path(arguments[3]).expanduser().resolve(strict=True)
    output = Path(arguments[4] if len(arguments) == 5 else ROOT / "build/codegen-perf-paired").expanduser().resolve()
    if not reference_bin.is_file() or not os.access(reference_bin, os.X_OK):
        raise SystemExit(f"reference compiler is not executable: {reference_bin}")
    if not candidate_bin.is_file() or not os.access(candidate_bin, os.X_OK):
        raise SystemExit(f"candidate compiler is not executable: {candidate_bin}")
    if not reference_root.is_dir() or not candidate_root.is_dir():
        raise SystemExit("both compiler source roots must be directories")
    reference_hash = digest(reference_bin)
    candidate_hash = digest(candidate_bin)
    if reference_hash == candidate_hash:
        raise SystemExit("reference and candidate compiler binaries are identical")

    raw_blocks = os.environ.get("PAIRED_BLOCKS", "1")
    if not raw_blocks.isdigit() or int(raw_blocks) < 1 or int(raw_blocks) > 99:
        raise SystemExit("PAIRED_BLOCKS must be an integer from 1 through 99")
    blocks = int(raw_blocks)

    lock_path = Path(os.environ.get("ELISA_BENCH_LOCK_PATH", "/tmp/elisa-cross-language-benchmark.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    complete = False
    output_owned = False
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"another benchmark holds the host lock at {lock_path}") from error
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            raise SystemExit(f"output directory is not empty: {output} (choose a fresh directory)")
        output_owned = True

        driver_sources = {
            "paired_wrapper": SCRIPT_DIR / "paired_cross_language.sh",
            "paired_runner": Path(__file__).resolve(),
            "paired_reporter": REPORTER,
            "process_counter": SCRIPT_DIR / "process_counter.py",
        }
        driver_hashes = {name: digest(path) for name, path in driver_sources.items()}
        arm_source_manifests = {
            "reference": source_manifest(reference_root),
            "candidate": source_manifest(candidate_root),
        }

        def assert_driver_sources_unchanged() -> None:
            for name, path in driver_sources.items():
                if digest(path) != driver_hashes[name]:
                    raise RuntimeError(f"paired benchmark driver changed during run: {path}")

        def assert_compiler_sources_unchanged() -> None:
            for role, source_root in (("reference", reference_root), ("candidate", candidate_root)):
                if source_manifest(source_root) != arm_source_manifests[role]:
                    raise RuntimeError(f"{role} compiler source inputs changed during paired run: {source_root}")

        reference_preflight_dir = output / "reference-preflight"
        candidate_preflight_dir = output / "candidate-preflight"
        print(f"Preparing reference compiler preflight: {reference_bin}", flush=True)
        run_suite(reference_bin, reference_root, reference_preflight_dir, lock_fd, preflight_only=True)
        reference_fingerprint = preflight_record(reference_preflight_dir, reference_bin, reference_root)
        assert_compiler_sources_unchanged()

        print(f"Preparing candidate compiler preflight: {candidate_bin}", flush=True)
        run_suite(
            candidate_bin,
            candidate_root,
            candidate_preflight_dir,
            lock_fd,
            preflight_only=True,
            reference_fingerprint=reference_preflight_dir / "canonical_workload_fingerprint.json",
        )
        candidate_fingerprint = preflight_record(candidate_preflight_dir, candidate_bin, candidate_root)
        assert_compiler_sources_unchanged()
        if (
            reference_fingerprint.get("fingerprint_sha256") != candidate_fingerprint.get("fingerprint_sha256")
            or reference_fingerprint.get("payload") != candidate_fingerprint.get("payload")
        ):
            raise RuntimeError("reference and candidate canonical workload fingerprints differ; no timed pairs were started")

        preflight_pair_metadata = {
            "reference_binary": str(reference_bin),
            "candidate_binary": str(candidate_bin),
        }
        try:
            reference_preflight_metadata = read_metadata(reference_preflight_dir / "metadata.txt")
            candidate_preflight_metadata = read_metadata(candidate_preflight_dir / "metadata.txt")
            verify_run_artifacts(reference_preflight_dir, reference_fingerprint, reference_preflight_metadata)
            verify_run_artifacts(candidate_preflight_dir, candidate_fingerprint, candidate_preflight_metadata)
            reference_identity = paired_input_identity(
                reference_fingerprint,
                preflight_pair_metadata,
                reference_preflight_metadata,
            )
            candidate_identity = paired_input_identity(
                candidate_fingerprint,
                preflight_pair_metadata,
                candidate_preflight_metadata,
            )
        except (OSError, ValueError) as error:
            raise RuntimeError(f"invalid paired preflight identity: {error}; no timed pairs were started") from error
        if reference_identity != candidate_identity:
            raise RuntimeError("reference and candidate preflight source or comparator toolchain identities differ; no timed pairs were started")

        paired_metadata = {
            "schema": "paired-cross-language-v1",
            "reference_binary": str(reference_bin),
            "reference_binary_sha256": reference_hash,
            "reference_source_root": str(reference_root),
            "reference_source_manifest": arm_source_manifests["reference"],
            "candidate_binary": str(candidate_bin),
            "candidate_binary_sha256": candidate_hash,
            "candidate_source_root": str(candidate_root),
            "candidate_source_manifest": arm_source_manifests["candidate"],
            "benchmark_root": str(ROOT.resolve()),
            "paired_wrapper": str(driver_sources["paired_wrapper"]),
            "paired_wrapper_sha256": driver_hashes["paired_wrapper"],
            "paired_runner": str(driver_sources["paired_runner"]),
            "paired_runner_sha256": driver_hashes["paired_runner"],
            "paired_reporter": str(driver_sources["paired_reporter"]),
            "paired_reporter_sha256": driver_hashes["paired_reporter"],
            "process_counter": str(driver_sources["process_counter"]),
            "process_counter_sha256": driver_hashes["process_counter"],
            "canonical_workload_fingerprint_sha256": reference_fingerprint["fingerprint_sha256"],
            "canonical_workload_payload": reference_fingerprint["payload"],
            "paired_order": "A-B-B-A",
            "paired_blocks": blocks,
        }
        (output / "paired_metadata.json").write_text(
            json.dumps(paired_metadata, indent=2, sort_keys=True) + "\n"
        )
        assert_driver_sources_unchanged()

        expected_fingerprint = reference_preflight_dir / "canonical_workload_fingerprint.json"
        for block in range(1, blocks + 1):
            prefix = f"block-{block:02d}"
            print(f"Paired block {block:02d} (A-B-B-A)", flush=True)
            run_suite(reference_bin, reference_root, output / f"{prefix}-A1-reference", lock_fd, reference_fingerprint=expected_fingerprint)
            assert_compiler_sources_unchanged()
            run_suite(candidate_bin, candidate_root, output / f"{prefix}-B1-candidate", lock_fd, reference_fingerprint=expected_fingerprint)
            assert_compiler_sources_unchanged()
            run_suite(candidate_bin, candidate_root, output / f"{prefix}-B2-candidate", lock_fd, reference_fingerprint=expected_fingerprint)
            assert_compiler_sources_unchanged()
            run_suite(reference_bin, reference_root, output / f"{prefix}-A2-reference", lock_fd, reference_fingerprint=expected_fingerprint)
            assert_compiler_sources_unchanged()
            assert_driver_sources_unchanged()

        subprocess.run([sys.executable, str(REPORTER), str(output)], check=True)
        assert_driver_sources_unchanged()
        assert_compiler_sources_unchanged()
        (output / "PAIRED_COMPLETE").write_text("paired A/B report complete\n")
        complete = True
        print(f"Paired comparison complete: {output / 'paired_ab_summary.csv'}")
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        if output_owned and not complete and not (output / "ABORTED.txt").exists():
            (output / "ABORTED.txt").write_text(
                f"ABORTED — paired benchmark failed. Partial runs are unusable.\n{error}\n"
            )
        print(str(error), file=sys.stderr)
        return 2
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
