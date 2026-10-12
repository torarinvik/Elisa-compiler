#!/usr/bin/env python3
"""Validate and summarize paired A/B output from paired_cross_language.sh."""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def metadata(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key] = value
    return result


def check_complete(directory: Path, scope: str) -> dict[str, object]:
    if (directory / "ABORTED.txt").exists():
        fail(f"{directory} is aborted")
    marker_name = "COMPILE_COMPLETE" if scope == "compile_only" else "COMPLETE"
    marker = directory / marker_name
    other = directory / ("COMPLETE" if marker_name == "COMPILE_COMPLETE" else "COMPILE_COMPLETE")
    if not marker.is_file() or marker.stat().st_size == 0 or other.exists():
        fail(f"{directory} has no successful {marker_name} marker")
    fingerprint = json.loads((directory / "canonical_workload_fingerprint.json").read_text())
    if fingerprint.get("payload", {}).get("scope") != scope:
        fail(f"{directory} has the wrong canonical workload scope")
    return fingerprint


def read_elisa_samples(path: Path) -> dict[str, dict[int, tuple[float, float]]]:
    if not path.is_file():
        fail(f"missing sample file: {path}")
    result: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"benchmark", "sample", "variant", "wall_seconds", "child_cpu_seconds"}
        if not required.issubset(reader.fieldnames or ()):
            fail(f"{path} is missing required columns: {sorted(required - set(reader.fieldnames or ())) }")
        for row in reader:
            if row["variant"] != "elisa":
                continue
            bench = row["benchmark"]
            sample = int(row["sample"])
            wall = float(row["wall_seconds"])
            cpu = float(row["child_cpu_seconds"])
            if not math.isfinite(wall) or wall <= 0 or not math.isfinite(cpu) or cpu <= 0:
                fail(f"{path} has a non-positive or non-finite timing for {bench}/sample {sample}")
            if sample in result[bench]:
                fail(f"{path} has duplicate Elisa sample {bench}/{sample}")
            result[bench][sample] = (wall, cpu)
    if not result:
        fail(f"{path} contains no Elisa samples")
    return dict(result)


def geometric_mean(values: list[float]) -> float:
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        fail("cannot compute a geometric mean from empty or invalid ratios")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        fail("usage: paired_report.py OUTPUT_DIR")
    out = Path(arguments[0]).resolve()
    pair_metadata = json.loads((out / "paired_metadata.json").read_text())
    scope = pair_metadata.get("canonical_workload_payload", {}).get("scope")
    if scope not in ("compile_only", "full_runtime"):
        fail("paired metadata has an invalid canonical workload scope")

    reference_preflight_dir = out / "reference-preflight"
    candidate_preflight_dir = out / "candidate-preflight"
    for directory in (reference_preflight_dir, candidate_preflight_dir):
        if not (directory / "PREFLIGHT_COMPLETE").is_file() or (directory / "ABORTED.txt").exists():
            fail(f"{directory} did not complete its exact correctness preflight")
    reference_preflight = json.loads((reference_preflight_dir / "canonical_workload_fingerprint.json").read_text())
    candidate_preflight = json.loads((candidate_preflight_dir / "canonical_workload_fingerprint.json").read_text())
    expected_fingerprint = pair_metadata.get("canonical_workload_fingerprint_sha256")
    if (
        reference_preflight.get("fingerprint_sha256") != expected_fingerprint
        or candidate_preflight.get("fingerprint_sha256") != expected_fingerprint
        or reference_preflight.get("payload") != candidate_preflight.get("payload")
    ):
        fail("preflight canonical fingerprints do not match the paired metadata")

    expected_hashes = {
        "reference": pair_metadata.get("reference_binary_sha256"),
        "candidate": pair_metadata.get("candidate_binary_sha256"),
    }
    blocks = sorted(path.name for path in out.glob("block-[0-9][0-9]-A1-reference"))
    if not blocks:
        fail("no completed A-B-B-A blocks were found")

    metric_files = {
        "compile": "compile_samples.csv",
        "build": "build_samples.csv",
    }
    if scope == "full_runtime":
        metric_files["runtime"] = "samples.csv"

    ratio_values: dict[str, dict[str, dict[str, list[float]]]] = {
        metric: defaultdict(lambda: {"wall": [], "cpu": []}) for metric in metric_files
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
                    for sample in sorted(reference_rows):
                        ref_wall, ref_cpu = reference_rows[sample]
                        cand_wall, cand_cpu = candidate_rows[sample]
                        pair_wall.append(cand_wall / ref_wall)
                        pair_cpu.append(cand_cpu / ref_cpu)
                    bench_values["wall"].extend(pair_wall)
                    bench_values["cpu"].extend(pair_cpu)
                    pair_summaries.append({
                        "metric": metric,
                        "block": block_number,
                        "pair": pair_number,
                        "benchmark": bench,
                        "matched_samples": len(pair_wall),
                        "median_candidate_over_reference_wall": statistics.median(pair_wall),
                        "median_candidate_over_reference_cpu": statistics.median(pair_cpu),
                    })

    summary_rows: list[dict[str, object]] = []
    for metric, workload_values in ratio_values.items():
        metric_rows: list[dict[str, object]] = []
        for bench in sorted(workload_values):
            wall = workload_values[bench]["wall"]
            cpu = workload_values[bench]["cpu"]
            row = {
                "metric": metric,
                "benchmark": bench,
                "matched_samples": len(wall),
                "median_candidate_over_reference_wall": statistics.median(wall),
                "geometric_mean_candidate_over_reference_wall": geometric_mean(wall),
                "median_candidate_over_reference_cpu": statistics.median(cpu),
                "geometric_mean_candidate_over_reference_cpu": geometric_mean(cpu),
            }
            summary_rows.append(row)
            metric_rows.append(row)
        if metric_rows:
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
            )
    print(f"Paired compiler A/B report: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
