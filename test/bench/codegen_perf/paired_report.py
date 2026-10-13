#!/usr/bin/env python3
"""Validate and summarize paired A/B output from paired_cross_language.sh."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from paired_runner import paired_input_identity, source_manifest, verified_timing_sample_bytes, verify_run_artifacts

SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_ROOT = SCRIPT_DIR.parents[2]


def fail(message: str) -> None:
    raise SystemExit(message)


def metadata(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key] = value
    return result


def check_fingerprint_record(directory: Path, fingerprint: dict[str, object], scope: str) -> None:
    payload = fingerprint.get("payload")
    if not isinstance(payload, dict) or payload.get("scope") != scope:
        fail(f"{directory} has the wrong canonical workload scope")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if fingerprint.get("fingerprint_sha256") != hashlib.sha256(canonical).hexdigest():
        fail(f"{directory} has an invalid canonical workload fingerprint")
    provenance = fingerprint.get("run_provenance")
    if not isinstance(provenance, dict):
        fail(f"{directory} has no run provenance")
    binding = json.dumps(
        {"payload": payload, "run_provenance": provenance},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if fingerprint.get("run_fingerprint_sha256") != hashlib.sha256(binding).hexdigest():
        fail(f"{directory} has an invalid run fingerprint")
    if fingerprint.get("runtime_artifact_sha256") != provenance.get("runtime_artifact_sha256"):
        fail(f"{directory} has inconsistent runtime artifact provenance")


def check_complete(directory: Path, scope: str) -> dict[str, object]:
    if (directory / "ABORTED.txt").exists():
        fail(f"{directory} is aborted")
    marker_name = "COMPILE_COMPLETE" if scope == "compile_only" else "COMPLETE"
    marker = directory / marker_name
    other = directory / ("COMPLETE" if marker_name == "COMPILE_COMPLETE" else "COMPILE_COMPLETE")
    if not marker.is_file() or marker.stat().st_size == 0 or other.exists():
        fail(f"{directory} has no successful {marker_name} marker")
    fingerprint = json.loads((directory / "canonical_workload_fingerprint.json").read_text())
    check_fingerprint_record(directory, fingerprint, scope)
    return fingerprint


SampleMetrics = tuple[float, float, int | None, int | None, str]


def read_elisa_samples(path: Path) -> dict[str, dict[int, SampleMetrics]]:
    try:
        sample_bytes = verified_timing_sample_bytes(path)
    except (OSError, ValueError) as error:
        fail(str(error))
    result: dict[str, dict[int, SampleMetrics]] = defaultdict(dict)
    try:
        sample_text = sample_bytes.decode("utf-8")
    except UnicodeDecodeError:
        fail(f"{path} is not valid UTF-8")
    with io.StringIO(sample_text, newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"benchmark", "sample", "variant", "wall_seconds", "child_cpu_seconds"}
        if not required.issubset(reader.fieldnames or ()):
            fail(f"{path} is missing required columns: {sorted(required - set(reader.fieldnames or ())) }")
        counter_fields = {"instructions_retired", "cycles_elapsed", "counter_status"}
        present_counter_fields = counter_fields.intersection(reader.fieldnames or ())
        if present_counter_fields and present_counter_fields != counter_fields:
            fail(f"{path} has incomplete counter columns")
        for row in reader:
            if row["variant"] != "elisa":
                continue
            bench = row["benchmark"]
            sample = int(row["sample"])
            wall = float(row["wall_seconds"])
            cpu = float(row["child_cpu_seconds"])
            if not math.isfinite(wall) or wall <= 0 or not math.isfinite(cpu) or cpu <= 0:
                fail(f"{path} has a non-positive or non-finite timing for {bench}/sample {sample}")
            if present_counter_fields:
                counter_status = row["counter_status"]
                if counter_status not in ("available", "unavailable"):
                    fail(f"{path} has an invalid counter status for {bench}/sample {sample}")
                if counter_status == "available":
                    try:
                        instructions = int(row["instructions_retired"])
                        cycles = int(row["cycles_elapsed"])
                    except (TypeError, ValueError):
                        fail(f"{path} has missing counters marked available for {bench}/sample {sample}")
                    if instructions <= 0 or cycles <= 0:
                        fail(f"{path} has non-positive counters for {bench}/sample {sample}")
                else:
                    if row["instructions_retired"] or row["cycles_elapsed"]:
                        fail(f"{path} has counter values marked unavailable for {bench}/sample {sample}")
                    instructions = cycles = None
            else:
                instructions = cycles = None
                counter_status = "unavailable"
            if sample in result[bench]:
                fail(f"{path} has duplicate Elisa sample {bench}/{sample}")
            result[bench][sample] = (wall, cpu, instructions, cycles, counter_status)
    if not result:
        fail(f"{path} contains no Elisa samples")
    return dict(result)


def validate_elisa_sample_coverage(
    samples: dict[str, dict[int, SampleMetrics]],
    metric: str,
    payload: dict[str, object],
    path: Path,
) -> None:
    workloads = payload.get("workloads")
    if not isinstance(workloads, list):
        fail(f"{path} canonical payload has no workload list")
    expected_workloads: set[str] = set()
    for workload in workloads:
        if not isinstance(workload, dict) or not isinstance(workload.get("name"), str) or not workload["name"]:
            fail(f"{path} canonical payload has a malformed workload")
        name = workload["name"]
        if name in expected_workloads:
            fail(f"{path} canonical payload has duplicate workload {name}")
        expected_workloads.add(name)
    if set(samples) != expected_workloads:
        missing = sorted(expected_workloads - set(samples))
        unexpected = sorted(set(samples) - expected_workloads)
        fail(f"{path} workload coverage differs from canonical payload (missing={missing}, unexpected={unexpected})")

    protocol = payload.get("measurement_protocol")
    repeat_key = "runtime_repeats" if metric == "runtime" else "build_repeats"
    repeat_count = protocol.get(repeat_key) if isinstance(protocol, dict) else None
    if type(repeat_count) is not int or repeat_count < 1:
        fail(f"{path} canonical payload has an invalid {repeat_key}")
    expected_samples = set(range(1, repeat_count + 1))
    for benchmark, rows in samples.items():
        if set(rows) != expected_samples:
            missing = sorted(expected_samples - set(rows))
            unexpected = sorted(set(rows) - expected_samples)
            fail(
                f"{path} sample coverage for {benchmark} differs from canonical {metric} repeats "
                f"(missing={missing}, unexpected={unexpected})"
            )


def geometric_mean(values: list[float]) -> float:
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        fail("cannot compute a geometric mean from empty or invalid ratios")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        fail("usage: paired_report.py OUTPUT_DIR")
    out = Path(arguments[0]).resolve()
    if (out / "ABORTED.txt").exists():
        fail(f"paired run is aborted: {(out / 'ABORTED.txt').read_text().strip()}")
    pair_metadata = json.loads((out / "paired_metadata.json").read_text())
    scope = pair_metadata.get("canonical_workload_payload", {}).get("scope")
    if scope not in ("compile_only", "full_runtime"):
        fail("paired metadata has an invalid canonical workload scope")
    if pair_metadata.get("benchmark_root") != str(BENCHMARK_ROOT.resolve()):
        fail("paired report is running from a different benchmark checkout")

    driver_artifacts = [
        ("paired_wrapper", "paired_wrapper_sha256"),
        ("paired_runner", "paired_runner_sha256"),
        ("paired_reporter", "paired_reporter_sha256"),
    ]
    if pair_metadata.get("process_counter") is not None:
        driver_artifacts.append(("process_counter", "process_counter_sha256"))
    for path_key, hash_key in driver_artifacts:
        driver_path = Path(str(pair_metadata.get(path_key, ""))).resolve()
        if not driver_path.is_file() or hashlib.sha256(driver_path.read_bytes()).hexdigest() != pair_metadata.get(hash_key):
            fail(f"paired benchmark driver changed: {driver_path}")

    expected_hashes = {
        "reference": pair_metadata.get("reference_binary_sha256"),
        "candidate": pair_metadata.get("candidate_binary_sha256"),
    }
    expected_roots = {
        "reference": Path(str(pair_metadata.get("reference_source_root", ""))).resolve(),
        "candidate": Path(str(pair_metadata.get("candidate_source_root", ""))).resolve(),
    }
    for role in ("reference", "candidate"):
        binary = Path(str(pair_metadata.get(f"{role}_binary", ""))).resolve()
        if not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest() != expected_hashes[role]:
            fail(f"{role} compiler binary changed during paired run")
        if source_manifest(expected_roots[role]) != pair_metadata.get(f"{role}_source_manifest"):
            fail(f"{role} compiler source files changed during paired run")

    reference_preflight_dir = out / "reference-preflight"
    candidate_preflight_dir = out / "candidate-preflight"
    for directory in (reference_preflight_dir, candidate_preflight_dir):
        if not (directory / "PREFLIGHT_COMPLETE").is_file() or (directory / "ABORTED.txt").exists():
            fail(f"{directory} did not complete its exact correctness preflight")
    reference_preflight = json.loads((reference_preflight_dir / "canonical_workload_fingerprint.json").read_text())
    candidate_preflight = json.loads((candidate_preflight_dir / "canonical_workload_fingerprint.json").read_text())
    check_fingerprint_record(reference_preflight_dir, reference_preflight, scope)
    check_fingerprint_record(candidate_preflight_dir, candidate_preflight, scope)
    for directory, role in ((reference_preflight_dir, "reference"), (candidate_preflight_dir, "candidate")):
        run_meta = metadata(directory / "metadata.txt")
        if run_meta.get("elisa_product_sha256") != expected_hashes[role]:
            fail(f"{directory} used a different {role} compiler binary")
        if run_meta.get("elisa_provenance_source_root") != str(expected_roots[role]):
            fail(f"{directory} used a different {role} compiler source root")
    expected_fingerprint = pair_metadata.get("canonical_workload_fingerprint_sha256")
    if (
        reference_preflight.get("fingerprint_sha256") != expected_fingerprint
        or candidate_preflight.get("fingerprint_sha256") != expected_fingerprint
        or reference_preflight.get("payload") != candidate_preflight.get("payload")
        or reference_preflight.get("payload") != pair_metadata.get("canonical_workload_payload")
    ):
        fail("preflight canonical fingerprints do not match the paired metadata")
    expected_blocks = pair_metadata.get("paired_blocks")
    if not isinstance(expected_blocks, int) or expected_blocks < 1 or expected_blocks > 99:
        fail("paired metadata has an invalid block count")
    block_paths = sorted(out.glob("block-*-A1-reference"))
    found_block_ids = []
    for path in block_paths:
        match = re.fullmatch(r"block-([0-9]+)-A1-reference", path.name)
        if match is None:
            fail(f"malformed paired block directory: {path.name}")
        found_block_ids.append(int(match.group(1)))
    blocks = [f"block-{index:02d}-A1-reference" for index in found_block_ids]
    expected_block_names = [f"block-{index:02d}-A1-reference" for index in range(1, expected_blocks + 1)]
    if found_block_ids != list(range(1, expected_blocks + 1)) or blocks != expected_block_names:
        fail("paired block directories are missing or do not match the declared block count")

    common_input_identity: dict[str, object] | None = None
    runtime_hashes_by_role: dict[str, str] = {}

    def require_common_inputs(
        fingerprint: dict[str, object], run_name: str, role: str, run_meta: dict[str, str]
    ) -> None:
        nonlocal common_input_identity
        try:
            verify_run_artifacts(out / run_name, fingerprint, run_meta)
            identity = paired_input_identity(fingerprint, pair_metadata, run_meta)
        except (OSError, ValueError) as error:
            fail(str(error))
        provenance = fingerprint["run_provenance"]
        if common_input_identity is None:
            common_input_identity = identity
        elif identity != common_input_identity:
            fail(f"{run_name} source or comparator toolchain identity differs from the paired runs")
        runtime_hash = provenance.get("runtime_artifact_sha256")
        if not isinstance(runtime_hash, str) or len(runtime_hash) != 64:
            fail(f"{run_name} has no valid runtime artifact hash")
        if role in runtime_hashes_by_role and runtime_hashes_by_role[role] != runtime_hash:
            fail(f"{run_name} rebuilt a different runtime artifact for the {role} compiler")
        runtime_hashes_by_role[role] = runtime_hash

    reference_preflight_metadata = metadata(reference_preflight_dir / "metadata.txt")
    candidate_preflight_metadata = metadata(candidate_preflight_dir / "metadata.txt")
    require_common_inputs(reference_preflight, "reference-preflight", "reference", reference_preflight_metadata)
    require_common_inputs(candidate_preflight, "candidate-preflight", "candidate", candidate_preflight_metadata)

    metric_files = {
        "compile": "compile_samples.csv",
        "build": "build_samples.csv",
    }
    if scope == "full_runtime":
        metric_files["runtime"] = "samples.csv"

    ratio_values: dict[str, dict[str, dict[str, list[float] | list[bool]]]] = {
        metric: defaultdict(lambda: {
            "wall": [], "cpu": [], "instructions": [], "cycles": [], "counter_complete": [],
        }) for metric in metric_files
    }
    pair_summaries: list[dict[str, object]] = []
    paired_runs: list[dict[str, str]] = []

    for block_path in blocks:
        block_number = block_path.split("-")[1]
        run_specs = (
            (f"block-{block_number}-A1-reference", "reference"),
            (f"block-{block_number}-B1-candidate", "candidate"),
            (f"block-{block_number}-B2-candidate", "candidate"),
            (f"block-{block_number}-A2-reference", "reference"),
        )
        checked: dict[str, tuple[dict[str, object], dict[str, str]]] = {}
        for run_name, role in run_specs:
            directory = out / run_name
            fingerprint = check_complete(directory, scope)
            if fingerprint.get("fingerprint_sha256") != expected_fingerprint:
                fail(f"{run_name} canonical workload fingerprint changed")
            run_meta = metadata(directory / "metadata.txt")
            if run_meta.get("elisa_product_sha256") != expected_hashes[role]:
                fail(f"{run_name} used a different {role} compiler binary")
            if run_meta.get("elisa_provenance_source_root") != str(expected_roots[role]):
                fail(f"{run_name} used a different {role} compiler source root")
            require_common_inputs(fingerprint, run_name, role, run_meta)
            checked[run_name] = (fingerprint, run_meta)

        pair_specs = (
            (1, f"block-{block_number}-A1-reference", f"block-{block_number}-B1-candidate"),
            (2, f"block-{block_number}-A2-reference", f"block-{block_number}-B2-candidate"),
        )
        for pair_number, reference_name, candidate_name in pair_specs:
            paired_runs.append({
                "block": block_number,
                "pair": str(pair_number),
                "reference": reference_name,
                "candidate": candidate_name,
            })
            for metric, filename in metric_files.items():
                reference_samples = read_elisa_samples(out / reference_name / filename)
                candidate_samples = read_elisa_samples(out / candidate_name / filename)
                expected_payload = reference_preflight["payload"]
                validate_elisa_sample_coverage(reference_samples, metric, expected_payload, out / reference_name / filename)
                validate_elisa_sample_coverage(candidate_samples, metric, expected_payload, out / candidate_name / filename)
                if reference_samples.keys() != candidate_samples.keys():
                    fail(f"{reference_name} and {candidate_name} have different {metric} workload sets")
                for bench in sorted(reference_samples):
                    reference_rows = reference_samples[bench]
                    candidate_rows = candidate_samples[bench]
                    if reference_rows.keys() != candidate_rows.keys():
                        fail(f"{reference_name} and {candidate_name} have different {metric} sample IDs for {bench}")
                    bench_values = ratio_values[metric][bench]
                    pair_wall: list[float] = []
                    pair_cpu: list[float] = []
                    pair_instructions: list[float] = []
                    pair_cycles: list[float] = []
                    for sample in sorted(reference_rows):
                        ref_wall, ref_cpu, ref_instructions, ref_cycles, ref_counter_status = reference_rows[sample]
                        cand_wall, cand_cpu, cand_instructions, cand_cycles, cand_counter_status = candidate_rows[sample]
                        pair_wall.append(cand_wall / ref_wall)
                        pair_cpu.append(cand_cpu / ref_cpu)
                        if (
                            ref_counter_status == "available"
                            and cand_counter_status == "available"
                            and ref_instructions is not None and cand_instructions is not None
                            and ref_cycles is not None and cand_cycles is not None
                        ):
                            pair_instructions.append(cand_instructions / ref_instructions)
                            pair_cycles.append(cand_cycles / ref_cycles)
                    bench_values["wall"].extend(pair_wall)
                    bench_values["cpu"].extend(pair_cpu)
                    pair_counters_available = (
                        len(pair_instructions) == len(pair_wall)
                        and len(pair_cycles) == len(pair_wall)
                    )
                    bench_values["counter_complete"].append(pair_counters_available)
                    if pair_counters_available:
                        bench_values["instructions"].extend(pair_instructions)
                        bench_values["cycles"].extend(pair_cycles)
                    pair_summaries.append({
                        "metric": metric,
                        "block": block_number,
                        "pair": pair_number,
                        "benchmark": bench,
                        "matched_samples": len(pair_wall),
                        "median_candidate_over_reference_wall": statistics.median(pair_wall),
                        "median_candidate_over_reference_cpu": statistics.median(pair_cpu),
                        "median_candidate_over_reference_instructions_retired": (
                            statistics.median(pair_instructions) if pair_counters_available else ""
                        ),
                        "median_candidate_over_reference_cycles_elapsed": (
                            statistics.median(pair_cycles) if pair_counters_available else ""
                        ),
                        "counter_status": "available" if pair_counters_available else "unavailable",
                    })

    summary_rows: list[dict[str, object]] = []
    for metric, workload_values in ratio_values.items():
        metric_rows: list[dict[str, object]] = []
        for bench in sorted(workload_values):
            wall = workload_values[bench]["wall"]
            cpu = workload_values[bench]["cpu"]
            instructions = workload_values[bench]["instructions"]
            cycles = workload_values[bench]["cycles"]
            counter_complete = workload_values[bench]["counter_complete"]
            counter_available = bool(counter_complete) and all(counter_complete)
            row = {
                "metric": metric,
                "benchmark": bench,
                "matched_samples": len(wall),
                "median_candidate_over_reference_wall": statistics.median(wall),
                "geometric_mean_candidate_over_reference_wall": geometric_mean(wall),
                "median_candidate_over_reference_cpu": statistics.median(cpu),
                "geometric_mean_candidate_over_reference_cpu": geometric_mean(cpu),
                "median_candidate_over_reference_instructions_retired": (
                    statistics.median(instructions) if counter_available else ""
                ),
                "geometric_mean_candidate_over_reference_instructions_retired": (
                    geometric_mean(instructions) if counter_available else ""
                ),
                "median_candidate_over_reference_cycles_elapsed": (
                    statistics.median(cycles) if counter_available else ""
                ),
                "geometric_mean_candidate_over_reference_cycles_elapsed": (
                    geometric_mean(cycles) if counter_available else ""
                ),
                "counter_status": "available" if counter_available else "unavailable",
            }
            summary_rows.append(row)
            metric_rows.append(row)
        if metric_rows:
            all_metric_counters_available = all(row["counter_status"] == "available" for row in metric_rows)
            summary_rows.append({
                "metric": metric,
                "benchmark": "geometric_mean",
                "matched_samples": sum(int(row["matched_samples"]) for row in metric_rows),
                "median_candidate_over_reference_wall": "",
                "geometric_mean_candidate_over_reference_wall": geometric_mean([
                    float(row["geometric_mean_candidate_over_reference_wall"]) for row in metric_rows
                ]),
                "median_candidate_over_reference_cpu": "",
                "geometric_mean_candidate_over_reference_cpu": geometric_mean([
                    float(row["geometric_mean_candidate_over_reference_cpu"]) for row in metric_rows
                ]),
                "median_candidate_over_reference_instructions_retired": "",
                "geometric_mean_candidate_over_reference_instructions_retired": (
                    geometric_mean([
                        float(row["geometric_mean_candidate_over_reference_instructions_retired"])
                        for row in metric_rows
                    ]) if all_metric_counters_available else ""
                ),
                "median_candidate_over_reference_cycles_elapsed": "",
                "geometric_mean_candidate_over_reference_cycles_elapsed": (
                    geometric_mean([
                        float(row["geometric_mean_candidate_over_reference_cycles_elapsed"])
                        for row in metric_rows
                    ]) if all_metric_counters_available else ""
                ),
                "counter_status": "available" if all_metric_counters_available else "unavailable",
            })

    summary_path = out / "paired_ab_summary.csv"
    fields = (
        "metric",
        "benchmark",
        "matched_samples",
        "median_candidate_over_reference_wall",
        "geometric_mean_candidate_over_reference_wall",
        "median_candidate_over_reference_cpu",
        "geometric_mean_candidate_over_reference_cpu",
        "median_candidate_over_reference_instructions_retired",
        "geometric_mean_candidate_over_reference_instructions_retired",
        "median_candidate_over_reference_cycles_elapsed",
        "geometric_mean_candidate_over_reference_cycles_elapsed",
        "counter_status",
    )
    with summary_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    pair_path = out / "paired_ab_pairs.csv"
    pair_fields = (
        "metric",
        "block",
        "pair",
        "benchmark",
        "matched_samples",
        "median_candidate_over_reference_wall",
        "median_candidate_over_reference_cpu",
        "median_candidate_over_reference_instructions_retired",
        "median_candidate_over_reference_cycles_elapsed",
        "counter_status",
    )
    with pair_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=pair_fields)
        writer.writeheader()
        writer.writerows(pair_summaries)

    report = {
        "schema": "paired-cross-language-report-v1",
        "scope": scope,
        "canonical_workload_fingerprint_sha256": expected_fingerprint,
        "paired_order": "A-B-B-A",
        "pair_count": len(paired_runs),
        "runtime_artifact_sha256_by_compiler": runtime_hashes_by_role,
        "pairs": paired_runs,
        "summary_csv": summary_path.name,
        "per_pair_csv": pair_path.name,
        "ratio_interpretation": "candidate/reference; values below 1.0 mean the candidate is faster",
        "summary": summary_rows,
    }
    (out / "paired_ab_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for row in summary_rows:
        if row["benchmark"] == "geometric_mean":
            print(
                f"{row['metric']}: candidate/reference geometric mean wall="
                f"{float(row['geometric_mean_candidate_over_reference_wall']):.4f}, child CPU="
                f"{float(row['geometric_mean_candidate_over_reference_cpu']):.4f}"
                + (
                    f", instructions={float(row['geometric_mean_candidate_over_reference_instructions_retired']):.4f}, "
                    f"cycles={float(row['geometric_mean_candidate_over_reference_cycles_elapsed']):.4f}"
                    if row["counter_status"] == "available" else ", counters=unavailable"
                )
            )
    print(f"Paired compiler A/B report: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
