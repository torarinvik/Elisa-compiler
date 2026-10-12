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
