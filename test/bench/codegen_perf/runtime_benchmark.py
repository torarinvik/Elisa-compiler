import csv
import hashlib
import json
import math
import os
import platform
import resource
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

out = Path(sys.argv[1])
repeat = int(sys.argv[2])
timeout_seconds = int(sys.argv[3])
root = Path(sys.argv[4])
source_dir = Path(sys.argv[5])
sys.path.insert(0, str(root / "scripts"))
sys.path.insert(0, str(source_dir))
from process_counter import (
    counters_available as retired_counters_available,
    method_description as counter_method_description,
    new_report_path as new_counter_report_path,
    read_report as read_counter_report,
    unavailable_counter,
    wrap_command as wrap_with_counter,
)
from bench_load_gate import LoadGateError, check_load_gate, load_average
benches = sys.argv[6:]
COUNTER_METHOD = counter_method_description()
COUNTERS_AVAILABLE = retired_counters_available()
if COUNTERS_AVAILABLE != (COUNTER_METHOD == "macOS /usr/bin/time -l"):
    raise SystemExit("retired-instruction counter availability changed during runtime startup")
variants = ("elisa", "c", "rust", "zig")
checksums = {}
exit_statuses = {}

def enforce_load_gate(load, stage):
    try:
        check_load_gate(load, stage, out, platform.system(), out / "host_qualification.json", require_live_linux=True)
    except LoadGateError as error:
        raise SystemExit(str(error)) from error

preflight_path = out / "correctness_preflight.json"
try:
    preflight = json.loads(preflight_path.read_text())
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"missing or invalid correctness preflight manifest {preflight_path}: {error}") from error
if preflight.get("schema") != "cross-language-correctness-v1":
    raise SystemExit(f"unsupported correctness preflight schema in {preflight_path}")
before_timing = preflight.get("before_timing")
after_build_samples = preflight.get("after_build_samples")
if not isinstance(before_timing, dict) or before_timing != after_build_samples:
    raise SystemExit(f"correctness preflight did not pass both before and after build samples: {preflight_path}")
if set(after_build_samples) != set(benches):
    raise SystemExit(f"correctness preflight workloads do not match this run: {preflight_path}")
manifest_path = out / "executables.after-build.sha256"
if preflight.get("executable_manifest") != manifest_path.name:
    raise SystemExit(f"correctness preflight references an unexpected executable artifact manifest: {preflight_path}")
try:
    manifest_bytes = manifest_path.read_bytes()
except OSError as error:
    raise SystemExit(f"missing executable artifact manifest {manifest_path}: {error}") from error
if hashlib.sha256(manifest_bytes).hexdigest() != preflight.get("executable_manifest_sha256"):
    raise SystemExit(f"executable artifact manifest does not match correctness preflight: {manifest_path}")
expected_artifacts = {}
for line in manifest_bytes.decode("utf-8").splitlines():
    digest, separator, relative_path = line.partition("  ")
    if not separator or len(digest) != 64 or relative_path in expected_artifacts:
        raise SystemExit(f"invalid executable artifact manifest row: {line!r}")
    expected_artifacts[relative_path] = digest
expected_artifact_paths = {f"{bench}/{variant}" for bench in benches for variant in variants}
if set(expected_artifacts) != expected_artifact_paths:
    raise SystemExit(f"executable artifact manifest does not match this run: {manifest_path}")

def artifact_manifest_text():
    rows = []
    for bench in benches:
        for variant in variants:
            binary = out / bench / variant
            relative_path = f"{bench}/{variant}"
            if not binary.is_file() or not binary.stat().st_mode & 0o111:
                raise SystemExit(f"missing executable artifact {binary}")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            rows.append(f"{digest}  {relative_path}\n")
    return "".join(rows)

def verify_artifact(bench, variant, stage):
    relative_path = f"{bench}/{variant}"
    binary = out / relative_path
    try:
        actual = hashlib.sha256(binary.read_bytes()).hexdigest()
    except OSError as error:
        raise SystemExit(f"could not verify executable artifact {binary} {stage}: {error}") from error
    if actual != expected_artifacts[relative_path]:
        raise SystemExit(f"executable artifact changed {stage}: {binary}")

for bench in benches:
    record = after_build_samples[bench]
    if not isinstance(record, dict) or not isinstance(record.get("checksum"), str) or not isinstance(record.get("exit_status"), int):
        raise SystemExit(f"invalid correctness preflight record for {bench}: {preflight_path}")
    checksums[bench] = record["checksum"].encode("utf-8")
    exit_statuses[bench] = record["exit_status"]

# Tie the post-build checksums to the exact final binaries before runtime timing starts.
if artifact_manifest_text().encode("utf-8") != manifest_bytes:
    raise SystemExit(f"executable artifacts changed after correctness preflight: {manifest_path}")
enforce_load_gate(load_average(), "before the first timed runtime sample")

times = {
    bench: {
        variant: {"wall": [], "cpu": [], "instructions": [], "cycles": [], "counter_status": []}
        for variant in variants
    }
    for bench in benches
}
counter_samples = []
raw_samples = []
for bench in benches:
    for sample in range(repeat):
        # Rotate launch order to reduce a fixed first/last variant bias.
        offset = sample % len(variants)
        order = variants[offset:] + variants[:offset]
        for launch_order, variant in enumerate(order):
            load_before = load_average()
            enforce_load_gate(load_before, f"before runtime sample {bench}/{variant}/{sample + 1}")
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            started = time.perf_counter_ns()
            binary = out / bench / variant
            report_path = new_counter_report_path(out)
            proc = subprocess.Popen(
                wrap_with_counter([str(binary)], report_path),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
                if report_path is not None:
                    report_path.unlink(missing_ok=True)
                raise RuntimeError(f"{bench}/{variant} exceeded {timeout_seconds}s timeout; process group killed") from error
            elapsed_ns = time.perf_counter_ns() - started
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            counter = read_counter_report(report_path) if report_path is not None else unavailable_counter()
            if report_path is not None:
                report_path.unlink(missing_ok=True)
            load_after = load_average()
            enforce_load_gate(load_after, f"after runtime sample {bench}/{variant}/{sample + 1}")
            if proc.returncode != exit_statuses[bench]:
                raise RuntimeError(f"timed status changed: {bench}/{variant} returned {proc.returncode}")
            if (stdout, stderr) not in ((checksums[bench], b""), (b"", checksums[bench])):
                raise RuntimeError(f"timed exact checksum output changed: {bench}/{variant}")
            verify_artifact(bench, variant, f"after runtime sample {bench}/{variant}/{sample + 1}")
            fallback_cpu = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
            cpu = counter.child_cpu_seconds if counter.child_cpu_seconds is not None else fallback_cpu
            wall = elapsed_ns / 1e9
            times[bench][variant]["wall"].append(wall)
            times[bench][variant]["cpu"].append(cpu)
            times[bench][variant]["instructions"].append(counter.instructions_retired)
            times[bench][variant]["cycles"].append(counter.cycles_elapsed)
            times[bench][variant]["counter_status"].append(counter.status)
            counter_samples.append((
                "runtime", bench, sample + 1, launch_order + 1, variant, "runtime",
                counter.instructions_retired, counter.cycles_elapsed, counter.child_cpu_seconds, counter.status,
            ))
            raw_samples.append((
                bench, sample + 1, launch_order + 1, variant, wall, cpu,
                counter.instructions_retired, counter.cycles_elapsed, counter.status,
                load_before[0], load_after[0],
            ))

runtime_manifest_bytes = artifact_manifest_text().encode("utf-8")
(out / "executables.after-runtime.sha256").write_bytes(runtime_manifest_bytes)
if runtime_manifest_bytes != manifest_bytes:
    raise SystemExit(f"executable artifacts changed during runtime sampling: {manifest_path}")

samples_path = out / "samples.csv"
with samples_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow((
        "benchmark", "sample", "launch_order", "variant", "wall_seconds", "child_cpu_seconds",
        "instructions_retired", "cycles_elapsed", "counter_status", "load1_before", "load1_after",
    ))
    for row in raw_samples:
        writer.writerow((
            *row[:4], f"{row[4]:.6f}", f"{row[5]:.6f}",
            "" if row[6] is None else str(row[6]),
            "" if row[7] is None else str(row[7]),
            row[8],
            "" if row[9] is None else f"{row[9]:.2f}",
            "" if row[10] is None else f"{row[10]:.2f}",
        ))

counter_samples_path = out / "counter_samples.csv"
with counter_samples_path.open("a", newline="") as stream:
    writer = csv.writer(stream)
    for row in counter_samples:
        writer.writerow((
            *row[:6],
            "" if row[6] is None else str(row[6]),
            "" if row[7] is None else str(row[7]),
            "" if row[8] is None else f"{row[8]:.6f}",
            row[9],
        ))

result_path = out / "results.csv"
with result_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow((
        "benchmark", "full_checksum", "exit_status", "variant",
        "best_wall_seconds", "median_wall_seconds", "best_child_cpu_seconds", "median_child_cpu_seconds",
        "median_instructions_retired", "median_cycles_elapsed", "counter_status", "repeat_count",
    ))
    for bench in benches:
        for variant in variants:
            samples = times[bench][variant]
            writer.writerow((
                bench,
                checksums[bench].decode("utf-8").strip(),
                exit_statuses[bench],
                variant,
                f"{min(samples['wall']):.6f}",
                f"{statistics.median(samples['wall']):.6f}",
                f"{min(samples['cpu']):.6f}",
                f"{statistics.median(samples['cpu']):.6f}",
                "" if any(value is None for value in samples["instructions"]) else str(int(statistics.median(samples["instructions"]))),
                "" if any(value is None for value in samples["cycles"]) else str(int(statistics.median(samples["cycles"]))),
                "available" if (
                    samples["instructions"] and all(value is not None for value in samples["instructions"])
                    and samples["cycles"] and all(value is not None for value in samples["cycles"])
                ) else "unavailable",
                len(samples["cpu"]),
            ))

runtime_ratio_fields = (
    ("elisa_over_rust_median_wall", "rust", "wall"),
    ("elisa_over_rust_median_child_cpu", "rust", "cpu"),
    ("elisa_over_rust_median_instructions_retired", "rust", "instructions"),
    ("elisa_over_rust_median_cycles_elapsed", "rust", "cycles"),
    ("elisa_over_zig_median_wall", "zig", "wall"),
    ("elisa_over_zig_median_child_cpu", "zig", "cpu"),
    ("elisa_over_zig_median_instructions_retired", "zig", "instructions"),
    ("elisa_over_zig_median_cycles_elapsed", "zig", "cycles"),
)
runtime_ratio_records = []
# The side-table read fixture uses volatile native accesses while Elisa emits
# ordinary helper accesses. Keep correctness and raw compile/build/runtime samples,
# but omit all cross-language ratios until both sides share that access contract.
diagnostic_only_benches = {"packed_side_table_read"}
runtime_comparison_benches = [bench for bench in benches if bench not in diagnostic_only_benches]
for bench in runtime_comparison_benches:
    record = {}
    for field, comparator, axis in runtime_ratio_fields:
        elisa_values = times[bench]["elisa"][axis]
        comparator_values = times[bench][comparator][axis]
        if axis in ("instructions", "cycles") and (
            not elisa_values or not comparator_values
            or any(value is None for value in elisa_values + comparator_values)
        ):
            record[field] = None
            continue
        elisa_median = statistics.median(elisa_values)
        comparator_median = statistics.median(comparator_values)
        if elisa_median <= 0 or comparator_median <= 0:
            raise RuntimeError(f"cannot compute positive median ratio for {bench}/{comparator}/{axis}")
        record[field] = elisa_median / comparator_median
    runtime_ratio_records.append(record)
runtime_ratio_means = {}
for field, _, axis in runtime_ratio_fields:
    values = [record[field] for record in runtime_ratio_records]
    runtime_ratio_means[field] = (
        math.exp(sum(math.log(value) for value in values) / len(values))
        if values and all(value is not None for value in values)
        else None
    )
runtime_ratio_path = out / "runtime_ratios.csv"
with runtime_ratio_path.open("w", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(("benchmark", *(field for field, _, _ in runtime_ratio_fields), "counter_status"))
    for bench, record in zip(runtime_comparison_benches, runtime_ratio_records):
        status = "available" if all(
            record[field] is not None
            for field, _, axis in runtime_ratio_fields if axis in ("instructions", "cycles")
        ) else "unavailable"
        writer.writerow((
            bench,
            *("" if record[field] is None else f"{record[field]:.6f}" for field, _, _ in runtime_ratio_fields),
            status,
        ))
    geometric_status = "available" if all(
        runtime_ratio_means[field] is not None
        for field, _, axis in runtime_ratio_fields if axis in ("instructions", "cycles")
    ) else "unavailable"
    writer.writerow((
        "geometric_mean",
        *("" if runtime_ratio_means[field] is None else f"{runtime_ratio_means[field]:.6f}" for field, _, _ in runtime_ratio_fields),
        geometric_status,
    ))

print("\nFull checksums and exit statuses matched in a separate preflight; timed fresh processes were checked again (repeat count per variant: " + str(repeat) + ")")
for metric, label in (("wall", "best/median wall seconds"), ("cpu", "best/median child CPU seconds")):
    print(f"\n{label}")
    print(f"{'benchmark':<30} {'checksum':>18} {'Elisa':>17} {'C':>17} {'Rust':>17} {'Zig':>17}")
    for bench in benches:
        values = []
        for variant in variants:
            samples = times[bench][variant][metric]
            values.append(f"{min(samples):.6f}/{statistics.median(samples):.6f}")
        checksum = checksums[bench].decode("utf-8").strip()
        label = f"{bench} (diagnostic-only)" if bench in diagnostic_only_benches else bench
        print(f"{label:<30} {checksum:>18} " + " ".join(f"{value:>17}" for value in values))
print("\nGenerated runtime Elisa/comparator median ratios (<1.0 means Elisa is faster; diagnostic-only workloads are omitted)")
print(f"{'benchmark':<20} {'Rust wall':>11} {'Rust CPU':>11} {'Rust instr':>11} {'Rust cycles':>11} {'Zig wall':>11} {'Zig CPU':>11} {'Zig instr':>11} {'Zig cycles':>11}")
for bench, record in zip(runtime_comparison_benches, runtime_ratio_records):
    values = [record[field] for field, _, _ in runtime_ratio_fields]
    print(f"{bench:<20} " + " ".join(f"{value:>11.3f}" if value is not None else f"{'n/a':>11}" for value in values))
values = [runtime_ratio_means[field] for field, _, _ in runtime_ratio_fields]
print(f"{'geometric mean':<20} " + " ".join(f"{value:>11.3f}" if value is not None else f"{'n/a':>11}" for value in values))
print(f"\nMetadata: {out / 'metadata.txt'}")
print(f"Sources:  {out / 'sources.sha256'}")
print(f"Compile:  {out / 'compile_results.csv'}")
print(f"Builds:   {out / 'build_results.csv'}")
print(f"Ratios:   {out / 'compile_ratios.csv'}, {out / 'build_ratios.csv'}, {runtime_ratio_path}")
print(f"Samples:  {samples_path}")
print(f"Results:  {result_path}")
print(f"Counters: {counter_samples_path}")
